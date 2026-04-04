from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_opus as bugnav


def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return 0 <= pos.x < w and 0 <= pos.y < h


# Tipos de edificios enemigos que nos interesa destruir y tapiar
_ENEMY_TARGETS = (
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
)

# Direcciones cardinales para elegir orientación del gunner
_CARDINALS = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)


def _building_points_to(c: Controller, bid: int, enemy_core: Position | None) -> bool:
    """
    Devuelve True si el edificio bid tiene su salida apuntando hacia el core enemigo.
    - Para BRIDGE: usa get_bridge_target y comprueba si el destino es el core.
    - Para CONVEYOR / ARMOURED_CONVEYOR / SPLITTER: usa get_direction y comprueba
      si la dirección va hacia el core enemigo (casilla destino == core).
    En cualquier error devuelve False.
    """
    if enemy_core is None:
        return False
    try:
        etype = c.get_entity_type(bid)
        pos = c.get_position(bid)
        if etype == EntityType.BRIDGE:
            dest = c.get_bridge_target(bid)
            return dest == enemy_core
        if etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER):
            d = c.get_direction(bid)
            # Seguir la dirección hasta salir del rango del edificio
            dest = pos.add(d)
            return dest == enemy_core
    except Exception:
        pass
    return False


class Muros:
    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()

        # Posición del core propio
        self.spawn: Position | None = None
        self.my_core: Position | None = None

        # Lógica de simetría para localizar el core enemigo (igual que Torreta)
        self.enemy_core_pos: Position | None = None
        self.enemy_core_candidates: list[Position] = []
        self.simetry: int = 0

        # Objetivo de destrucción actual
        self.objetivo: Position | None = None

        # True si el edificio objetivo apuntaba al core enemigo (→ poner gunner)
        self.objetivo_apunta_core: bool = False

        # Casillas donde hemos colocado una barrier y queremos confirmarla
        self.barriers_placed: set[Position] = set()

        # Inicialización: localizar core propio y calcular candidatos del enemigo
        builds = ct.get_nearby_buildings()
        for b in builds:
            if ct.get_entity_type(b) == EntityType.CORE:
                self.spawn = ct.get_position(b)
                self.my_core = self.spawn
                break

        if self.my_core is not None:
            w = ct.get_map_width()
            h = ct.get_map_height()
            x = self.my_core.x
            y = self.my_core.y
            self.enemy_core_candidates = [
                Position(w - 1 - x, y),
                Position(x, h - 1 - y),
                Position(w - 1 - x, h - 1 - y),
            ]

    # ──────────────────────────────────────────────────────────────────────────
    # Punto de entrada principal
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, c: Controller):
        current = c.get_position()

        if c.can_heal(current):
            c.heal(current)
            
        # ── Inicialización tardía si el __init__ no encontró el core ──────────
        if self.my_core is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) == c.get_team():
                    self.my_core = c.get_position(b)
                    self.spawn = self.my_core
                    w = c.get_map_width()
                    h = c.get_map_height()
                    x = self.my_core.x
                    y = self.my_core.y
                    self.enemy_core_candidates = [
                        Position(w - 1 - x, y),
                        Position(x, h - 1 - y),
                        Position(w - 1 - x, h - 1 - y),
                    ]
                    break

        # ── 1. Escanear enemigos en visión y actualizar objetivo ───────────────
        self._scan_enemies(c)

        # ── 2. Si tenemos objetivo, trabajar en él ────────────────────────────
        if self.objetivo is not None:
            c.draw_indicator_dot(current, 255, 80, 0)       # naranja: tengo objetivo
            c.draw_indicator_line(current, self.objetivo, 255, 80, 0)
            self._work_objetivo(c)
            return

        # ── 3. Sin objetivo: buscar/explorar ─────────────────────────────────
        if self.enemy_core_pos is None:
            c.draw_indicator_dot(current, 255, 255, 0)      # amarillo: buscando core
            self._find_enemy_core(c)
        else:
            c.draw_indicator_dot(current, 100, 100, 255)    # azul: explorando
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            move_pos = current.add(move_dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(move_dir):
                c.move(move_dir)

    # ──────────────────────────────────────────────────────────────────────────
    # Escaneo de edificios enemigos en visión
    # ──────────────────────────────────────────────────────────────────────────

    def _scan_enemies(self, c: Controller):
        """
        Recorre los edificios en visión y elige como objetivo el edificio enemigo
        más cercano (conveyor, armoured conveyor, bridge o splitter).
        Si el objetivo actual sigue siendo válido se mantiene; si ya no existe
        (lo destruimos o salió de visión) se busca uno nuevo.
        """
        current = c.get_position()

        # Validar objetivo actual
        if self.objetivo is not None:
            if c.is_in_vision(self.objetivo):
                bid = c.get_tile_building_id(self.objetivo)
                if bid is None or c.get_team(bid) == c.get_team():
                    # Ya no hay enemigo ahí: limpiar objetivo
                    self.objetivo = None
            # Si no está en visión, lo mantenemos y nos acercamos

        # Buscar nuevo objetivo si no tenemos
        if self.objetivo is None:
            best_pos: Position | None = None
            best_dist = float("inf")
            best_bid: int | None = None

            for bid in c.get_nearby_buildings():
                if c.get_team(bid) == c.get_team():
                    continue
                if c.get_entity_type(bid) not in _ENEMY_TARGETS:
                    continue
                pos = c.get_position(bid)
                dist = current.distance_squared(pos)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = pos
                    best_bid = bid

            self.objetivo = best_pos
            self.objetivo_apunta_core = (
                _building_points_to(c, best_bid, self.enemy_core_pos)
                if best_bid is not None else False
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Trabajar sobre el objetivo: destruir y tapar con barrier
    # ──────────────────────────────────────────────────────────────────────────

    def _work_objetivo(self, c: Controller):
        """
        Flujo:
        1. Si no estamos en visión del objetivo, acercarnos.
        2. Si hay un edificio enemigo: movernos encima y atacarlo (fire).
           Si acabamos de movernos y ahora estamos encima, atacamos en el mismo turno.
        3. Si la casilla quedó libre: construir un GUNNER (apuntando al core enemigo)
           si el edificio destruido apuntaba al core, o una BARRIER en caso contrario.
           Si estamos encima, salir primero.
        4. Si ya hay nuestro edificio en la casilla, marcar objetivo como resuelto.
        """
        current = c.get_position()
        target = self.objetivo

        # ── Acercarse si no está en visión ────────────────────────────────────
        if not c.is_in_vision(target):
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            move_pos = current.add(dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        bid = c.get_tile_building_id(target)

        # ── Casilla libre o ya es nuestra: colocar el edificio defensivo ──────
        if bid is None or c.get_team(bid) == c.get_team():
            if bid is not None:
                etype = c.get_entity_type(bid)
                if etype in (EntityType.BARRIER, EntityType.GUNNER) and c.get_team(bid) == c.get_team():
                    # Ya tenemos nuestro edificio ahí: objetivo completado
                    self.objetivo = None
                    return
                # Road u otro edificio aliado que sobró: destruir y esperar
                if c.can_destroy(target):
                    c.destroy(target)
                return

            # Si estamos encima, salir primero para poder construir
            if current == target:
                for d in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
                          Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST):
                    adj = target.add(d)
                    if _is_in_bounds(c, adj) and c.can_move(d):
                        c.move(d)
                        return
                return

            # Intentar construir en rango
            dist_sq = current.distance_squared(target)
            if dist_sq <= 2:
                if self.objetivo_apunta_core and self.enemy_core_pos is not None:
                    # Gunner apuntando al core enemigo
                    gun_dir = target.direction_to(self.enemy_core_pos)
                    if c.can_build_gunner(target, gun_dir):
                        c.build_gunner(target, gun_dir)
                        self.objetivo = None
                else:
                    if c.can_build_barrier(target):
                        c.build_barrier(target)
                        self.objetivo = None
                # Si no podemos aún (cooldown/recursos), esperamos el turno siguiente
            else:
                dir = self.navegador.moveTo(c, target, four_dirs=False)
                move_pos = current.add(dir)
                if c.can_build_road(move_pos):
                    c.build_road(move_pos)
                if c.can_move(dir):
                    c.move(dir)
            return

        # ── Hay edificio enemigo: necesitamos estar ENCIMA para atacar ────────
        if current == target:
            if c.can_fire(target):
                c.fire(target)
            return

        # Intentar movernos encima. Si lo logramos, atacar en el mismo turno.
        moved = False
        if c.is_tile_passable(target):
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            move_pos = current.add(dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(dir):
                c.move(dir)
                moved = True
        else:
            # Edificio sólido: acercarnos lo máximo posible
            dist_sq = current.distance_squared(target)
            if dist_sq > 2:
                dir = self.navegador.moveTo(c, target, four_dirs=False)
                move_pos = current.add(dir)
                if c.can_build_road(move_pos):
                    c.build_road(move_pos)
                if c.can_move(dir):
                    c.move(dir)
                    moved = True

        # Si tras movernos estamos encima, atacar ahora mismo
        if moved and c.get_position() == target:
            if c.can_fire(target):
                c.fire(target)

    # ──────────────────────────────────────────────────────────────────────────
    # Búsqueda del core enemigo por simetría (igual que Torreta)
    # ──────────────────────────────────────────────────────────────────────────

    def _find_enemy_core(self, c: Controller):
        if not self.enemy_core_candidates:
            return

        target = self.enemy_core_candidates[self.simetry % len(self.enemy_core_candidates)]
        current = c.get_position()

        c.draw_indicator_line(current, target, 255, 140, 0)

        dir = self.navegador.moveTo(c, target, four_dirs=False)
        move_pos = current.add(dir)
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(dir):
            c.move(dir)

        # Comprobar si alcanzamos el core enemigo en la posición estimada
        if c.is_in_vision(target):
            bid = c.get_tile_building_id(target)
            if bid is not None and c.get_entity_type(bid) == EntityType.CORE and c.get_team(bid) != c.get_team():
                self.enemy_core_pos = target
            else:
                self.simetry += 1

        # También detectarlo si aparece en el radar por cualquier dirección
        for b in c.get_nearby_buildings():
            if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team():
                self.enemy_core_pos = c.get_position(b)
                break