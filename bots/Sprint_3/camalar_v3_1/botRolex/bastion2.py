from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav

# ---------------------------------------------------------------------------
# BASTION BOT
# Construye un anillo de barriers alrededor del core con forma de doble
# cuadrado (11×11 en esquinas y laterales, 13×13 en los cardinales).
#
# Flujo general:
#   1. Localiza el core y calcula las 48 posiciones objetivo.
#   2. Cada vez que termina un target, elige el más cercano de los pendientes.
#   3. Para cada objetivo: se acerca (poniendo roads), construye la barrier.
#   4. Si una barrier propia bloquea el paso, la destruye, pone road, se mueve
#      y la registra en `to_restore` para devolverla cuando vuelva a estar en rango.
#   5. En modo patrol: recorre el anillo reparando lo que el enemigo destruya.
# ---------------------------------------------------------------------------

def _is_in_bounds_static(x: int, y: int, w: int, h: int) -> bool:
    return 0 <= x < w and 0 <= y < h


# Offsets relativos al CENTRO del core que forman el anillo de barriers.
#
#   1. Del borde del cuadrado 11x11 (|dx|==5 OR |dy|==5):
#      todas EXCEPTO aquellas con |dx|<=1 O |dy|<=1
#
#   2. Del borde del cuadrado 13x13 (|dx|==6 OR |dy|==6):
#      solo aquellas con |dx|<=2 O |dy|<=2
#
# Resultado: 48 posiciones con anillo con muescas en los 4 cardinales.
_BARRIER_OFFSETS: list[tuple[int, int]] = []
_seen: set[tuple[int, int]] = set()

for _dx in range(-5, 6):
    for _dy in range(-5, 6):
        if (abs(_dx) == 5 or abs(_dy) == 5) and not (abs(_dx) <= 1 or abs(_dy) <= 1):
            if (_dx, _dy) not in _seen:
                _BARRIER_OFFSETS.append((_dx, _dy))
                _seen.add((_dx, _dy))

for _dx in range(-6, 7):
    for _dy in range(-6, 7):
        if (abs(_dx) == 6 or abs(_dy) == 6) and (abs(_dx) <= 2 or abs(_dy) <= 2):
            if (_dx, _dy) not in _seen:
                _BARRIER_OFFSETS.append((_dx, _dy))
                _seen.add((_dx, _dy))

del _seen, _dx, _dy


class Bastion:
    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()

        self.map_w = ct.get_map_width()
        self.map_h = ct.get_map_height()

        # Localizar core
        self.core_center: Position | None = None
        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) == EntityType.CORE and ct.get_team(b) == ct.get_team():
                self.core_center = ct.get_position(b)

        # Lista completa de targets válidos
        self.all_targets: list[Position] = []
        # Conjunto de targets pendientes (no resueltos aún)
        self.pending: set[Position] = set()

        if self.core_center is not None:
            cx, cy = self.core_center.x, self.core_center.y
            for dx, dy in _BARRIER_OFFSETS:
                p = Position(cx + dx, cy + dy)
                if self._in_bounds(p):
                    self.all_targets.append(p)
                    self.pending.add(p)

        # Target activo actual (None = hay que elegir el más cercano)
        self.current_target: Position | None = None

        # Barriers propias destruidas temporalmente; hay que restaurarlas
        self.to_restore: set[Position] = set()

        # Modo: "build" construyendo el anillo, "patrol" reparando
        self._mode: str = "build"

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _in_bounds(self, pos: Position) -> bool:
        return _is_in_bounds_static(pos.x, pos.y, self.map_w, self.map_h)

    def _target_resolved(self, c: Controller, pos: Position) -> bool:
        """True si la posición ya tiene barrier aliada o muro de mapa."""
        if not c.is_in_vision(pos):
            return False
        if c.get_tile_env(pos) == Environment.WALL:
            return True
        bid = c.get_tile_building_id(pos)
        if bid is not None:
            return (c.get_entity_type(bid) == EntityType.BARRIER
                    and c.get_team(bid) == c.get_team())
        return False

    def _pick_nearest(self, c: Controller, pool) -> Position | None:
        """Devuelve la posición más cercana de `pool` a la posición actual."""
        if not pool:
            return None
        my_pos = c.get_position()
        return min(pool, key=lambda p: my_pos.distance_squared(p))

    # -----------------------------------------------------------------------
    # Destrucción de barriers propias para abrir paso
    # -----------------------------------------------------------------------

    def _clear_own_barrier_at(self, c: Controller, pos: Position) -> bool:
        """
        Si hay una barrier propia en `pos` y estamos en rango (dist²≤2):
        la destruye, pone road y la registra para restaurar.
        Devuelve True si la casilla quedó libre (o ya lo estaba).
        """
        if not self._in_bounds(pos) or not c.is_in_vision(pos):
            return False
        bid = c.get_tile_building_id(pos)
        if bid is None:
            return True
        if not (c.get_entity_type(bid) == EntityType.BARRIER
                and c.get_team(bid) == c.get_team()):
            return True  # no es barrier propia, no actuamos aquí
        if c.get_position().distance_squared(pos) <= 2 and c.can_destroy(pos):
            c.destroy(pos)
            # Registrar SIEMPRE para restaurar, aunque no podamos poner road ahora
            self.to_restore.add(pos)
            if c.can_build_road(pos):
                c.build_road(pos)
            return True
        return False

    # -----------------------------------------------------------------------
    # Movimiento seguro
    # -----------------------------------------------------------------------

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        """
        Intenta moverse en `direction`.
        Si hay una barrier propia en el destino, la destruye (pone road) y se mueve.
        Registra la posición en to_restore.
        Devuelve True si se movió.
        """
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not self._in_bounds(dest):
            return False

        bid = c.get_tile_building_id(dest)
        if (bid is not None
                and c.get_entity_type(bid) == EntityType.BARRIER
                and c.get_team(bid) == c.get_team()):
            if c.can_destroy(dest):
                c.destroy(dest)
                # Registrar SIEMPRE para restaurar, aunque no podamos poner road ahora
                self.to_restore.add(dest)
                if c.can_build_road(dest):
                    c.build_road(dest)
                if c.can_move(direction):
                    c.move(direction)
                    return True
            return False

        if c.can_move(direction):
            c.move(direction)
            return True
        return False

    # -----------------------------------------------------------------------
    # Restauración de barriers temporalmente destruidas
    # -----------------------------------------------------------------------

    def _restore_barriers(self, c: Controller) -> bool:
        """
        Restaura barriers que destruimos para pasar, cuando volvemos a estar en rango.
        Limpia cualquier cosa que haya en la casilla antes de poner la barrier.

        Reglas clave:
        - NO restaurar si estamos encima (dist²==0): aún estamos pasando.
        - Si hay barriers pendientes en rango pero no tenemos recursos, esperar
          aquí (devuelve True para que run() no ejecute ninguna otra lógica).

        Devuelve True  si el bot debe quedarse bloqueado esperando recursos.
        Devuelve False si no hay nada pendiente en rango (el bot puede continuar).
        """
        if not self.to_restore:
            return False

        my_pos = c.get_position()
        done = set()
        waiting_for_resources = False

        for pos in list(self.to_restore):
            # No restaurar si estamos encima — aún estamos "usando" el paso
            if my_pos == pos:
                continue

            # Solo actuamos si estamos en rango de acción (dist² <= 2)
            if my_pos.distance_squared(pos) > 2:
                continue

            if not c.is_in_vision(pos):
                continue

            bid = c.get_tile_building_id(pos)

            # Ya restaurada
            if (bid is not None
                    and c.get_entity_type(bid) == EntityType.BARRIER
                    and c.get_team(bid) == c.get_team()):
                done.add(pos)
                continue

            # Hay algo en la casilla: quitarlo primero
            if bid is not None:
                if c.can_destroy(pos):
                    c.destroy(pos)
                # Si era enemigo y no podemos destruir, olvidarlo
                elif c.get_team(bid) != c.get_team():
                    done.add(pos)
                continue  # intentar en turno siguiente

            # Casilla libre: construir barrier o esperar recursos
            if c.can_build_barrier(pos):
                c.build_barrier(pos)
                done.add(pos)
            else:
                # No hay recursos suficientes: quedarnos aquí hasta tenerlos
                waiting_for_resources = True

        self.to_restore -= done
        return waiting_for_resources

    # -----------------------------------------------------------------------
    # Navegación
    # -----------------------------------------------------------------------

    def _navigate_to(self, c: Controller, target: Position):
        """
        Navega hacia target poniendo roads. Si el siguiente paso tiene una barrier
        propia, la destruye para abrir paso y la añade a to_restore.
        """
        current = c.get_position()
        direction = self.navegador.moveTo(c, target, four_dirs=False)
        if direction == Direction.CENTRE:
            return
        next_pos = current.add(direction)
        if self._in_bounds(next_pos):
            # Limpiar barrier propia si bloquea el paso
            self._clear_own_barrier_at(c, next_pos)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
        self._try_move(c, direction)

    # -----------------------------------------------------------------------
    # Construcción de una barrier en una posición objetivo
    # -----------------------------------------------------------------------

    def _build_barrier_at(self, c: Controller, target: Position) -> bool:
        """
        Intenta construir una barrier en `target`.
        Devuelve True  si la posición quedó resuelta.
        Devuelve False si necesita más turnos.
        """
        if not c.is_in_vision(target):
            self._navigate_to(c, target)
            return False

        if c.get_tile_env(target) == Environment.WALL:
            return True
        
        valid = [EntityType.BARRIER, EntityType.BREACH, EntityType.SENTINEL, EntityType.GUNNER, EntityType.HARVESTER]

        bid = c.get_tile_building_id(target)
        my_pos = c.get_position()

        # Ya tiene barrier aliada
        if (bid is not None
                and c.get_entity_type(bid) in valid
                and c.get_team(bid) == c.get_team()):
            return True

        if bid is not None:
            etype = c.get_entity_type(bid)
            team = c.get_team(bid)

            # Road propia: destruir y esperar
            if etype == EntityType.ROAD and team == c.get_team():
                if my_pos.distance_squared(target) <= 2 and c.can_destroy(target):
                    c.destroy(target)
                else:
                    self._navigate_to(c, target)
                return False

            # Road enemiga: ir encima y atacar
            if etype == EntityType.ROAD and team != c.get_team():
                if my_pos == target:
                    if c.can_fire(target):
                        c.fire(target)
                    if c.get_tile_building_id(target) is None:
                        for d in [Direction.NORTH, Direction.EAST,
                                  Direction.SOUTH, Direction.WEST]:
                            if self._try_move(c, d):
                                break
                else:
                    if c.is_tile_passable(target):
                        self._navigate_to(c, target)
                return False

            # Marker: ignorar (no bloquea construcción)
            if etype == EntityType.MARKER:
                pass

            else:
                # Otro edificio aliado: destruir
                if team == c.get_team():
                    if my_pos.distance_squared(target) <= 2 and c.can_destroy(target):
                        c.destroy(target)
                    else:
                        self._navigate_to(c, target)
                    return False
                # Enemigo no-road: skip permanente
                return True

        # Casilla vacía (o solo marker): construir
        dist = my_pos.distance_squared(target)

        if dist == 0:
            # Estamos encima: salir primero
            for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
                if self._in_bounds(target.add(d)) and self._try_move(c, d):
                    break
            return False

        if dist > 2:
            self._navigate_to(c, target)
            return False

        # En rango (dist² ∈ {1, 2}): construir
        if c.can_build_barrier(target):
            c.build_barrier(target)
            return True

        return False

    # -----------------------------------------------------------------------
    # Lógica principal
    # -----------------------------------------------------------------------

    def run(self, c: Controller):
        # Localizar core si aún no lo tenemos
         # Si no encontramos el core aún (no debería pasar normalmente), buscar
        if self.core_center is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) == c.get_team():
                    self.core_center = c.get_position(b)
            if self.core_center is None:
                return

        # 1. Restaurar barriers temporalmente destruidas.
        # Si devuelve True, hay barriers en rango pendientes de reconstruir
        # pero sin recursos: quedarse quieto este turno.
        if self._restore_barriers(c):
            return

        # 2. Ejecutar según modo
        if self._mode == "build":
            self._build_mode(c)
        else:
            pass
            #self._patrol_mode(c)

    # -----------------------------------------------------------------------
    # Modo BUILD
    # -----------------------------------------------------------------------

    def _build_mode(self, c: Controller):
        """
        Construye el anillo eligiendo siempre el target pendiente más cercano.
        No cambia de target hasta resolver el actual.
        """
        if not self.pending:
            self._mode = "patrol"
            return

        # Elegir target si no tenemos uno activo o el actual ya fue resuelto
        if self.current_target is None or self.current_target not in self.pending:
            self.current_target = self._pick_nearest(c, self.pending)

        if self.current_target is None:
            self._mode = "patrol"
            return

        target = self.current_target
        c.draw_indicator_dot(target, 200, 100, 255)
        c.draw_indicator_line(c.get_position(), target, 180, 80, 255)

        resolved = self._build_barrier_at(c, target)
        if resolved:
            self.pending.discard(target)
            self.current_target = None  # siguiente turno elige el más cercano

    # -----------------------------------------------------------------------
    # Modo PATROL
    # -----------------------------------------------------------------------

    def _patrol_mode(self, c: Controller):
        """
        Repara barriers destruidas. Elige la más cercana entre las visibles y rotas.
        Si no hay ninguna rota visible, patrulla moviéndose por el anillo.
        """
        if not self.all_targets:
            return

        my_pos = c.get_position()

        # Targets visibles y no resueltos
        broken_visible = [
            p for p in self.all_targets
            if c.is_in_vision(p) and not self._target_resolved(c, p)
        ]

        if broken_visible:
            # Elegir el más cercano si no hay target activo o el actual ya está bien
            if (self.current_target is None
                    or self._target_resolved(c, self.current_target)
                    or self.current_target not in broken_visible):
                self.current_target = min(
                    broken_visible, key=lambda p: my_pos.distance_squared(p)
                )

            target = self.current_target
            c.draw_indicator_dot(target, 255, 80, 80)
            c.draw_indicator_line(my_pos, target, 255, 60, 60)

            resolved = self._build_barrier_at(c, target)
            if resolved:
                self.current_target = None
            return

        # Nada roto visible: moverse hacia el punto más lejano del anillo
        # para ir cubriendo todo el perímetro con el tiempo
        if (self.current_target is None
                or my_pos.distance_squared(self.current_target) <= 4):
            self.current_target = max(
                self.all_targets, key=lambda p: my_pos.distance_squared(p)
            )

        target = self.current_target
        c.draw_indicator_dot(target, 100, 255, 100)
        self._navigate_to(c, target)