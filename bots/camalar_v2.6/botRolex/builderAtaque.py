from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bignav_opus as bugnav


def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return 0 <= pos.x < w and 0 <= pos.y < h


def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0


def _cardinal_dirs():
    return [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]


def _conveyor_dir_to_core(tile: Position, core_pos: Position) -> Direction:
    dx = core_pos.x - tile.x
    dy = core_pos.y - tile.y
    if dx == 0 and dy == 0:
        return Direction.CENTRE
    if abs(dx) >= abs(dy):
        return Direction.EAST if dx > 0 else Direction.WEST
    else:
        return Direction.SOUTH if dy > 0 else Direction.NORTH


class BuilderAtaque:
    """
    Bot de ataque con cadena de conveyors.

    Fases:
      0 - ESPERA: permanece en la base, cura aliados y repara conveyors visibles.
      1 - BUSCAR_SPLITTER: busca el splitter construido por defensivo.py y calcula
          la casilla de origen de la cadena (adyacente al splitter, hacia el enemigo).
      2 - CADENA: construye conveyors avanzando hacia el core enemigo.
          Si detecta una torreta enemiga en visión, activa la fase 3.
          Si ve el core enemigo, activa la fase 4.
      3 - REFUERZO: construye un splitter + 2 sentinels a los lados y luego vuelve
          a la fase 2 para continuar la cadena.
      4 - ASALTO_FINAL: construye un splitter + 3 sentinels (lados + frente) junto
          al core enemigo y termina.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # Inicialización
    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()

        self.map_w = ct.get_map_width()
        self.map_h = ct.get_map_height()

        # Posición del core propio
        self.my_core: Position | None = None
        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) == EntityType.CORE:
                self.my_core = ct.get_position(b)
                break

        # Posibles posiciones del core enemigo (tres simetrías)
        self.enemy_core_pos: Position | None = None
        self.enemy_core_candidates: list[Position] = []
        self.symmetry_idx: int = 0
        if self.my_core is not None:
            x, y = self.my_core.x, self.my_core.y
            w, h = self.map_w, self.map_h
            self.enemy_core_candidates = [
                Position(w - 1 - x, y),
                Position(x, h - 1 - y),
                Position(w - 1 - x, h - 1 - y),
            ]

        # ── Variables de fase ──────────────────────────────────────────────
        self.fase: int = 0  # 0=ESPERA, 1=BUSCAR_SPLITTER, 2=CADENA, 3=REFUERZO, 4=ASALTO_FINAL

        # Splitter de defensivo
        self.splitter_pos: Position | None = None

        # Cabeza de la cadena: posición donde colocaremos el próximo conveyor
        self.chain_head: Position | None = None

        # Dirección principal de avance de la cadena (hacia el enemigo)
        self.advance_dir: Direction | None = None

        # Número de conveyors puestos en la cadena (para debug / límite)
        self.conveyors_built: int = 0

        # Dirección del conveyor que se está posicionando (desde chain_head hacia atrás)
        # Los conveyors apuntan de vuelta hacia el core propio para llevar recursos.
        # La cadena avanza, pero queremos recursos fluyendo hacia adelante (al enemigo).
        # En realidad queremos que los conveyors lleven recursos HACIA ADELANTE, así que
        # cada conveyor apunta en la dirección de avance (hacia el siguiente).
        # El primer conveyor recibe del splitter y apunta hacia el siguiente de la cadena.

        # ── Refuerzo / asalto ─────────────────────────────────────────────
        # Cuando detectamos una amenaza o el core, guardamos el punto donde
        # construiremos el splitter de refuerzo.
        self.refuerzo_pos: Position | None = None        # donde poner el splitter de refuerzo
        self.refuerzo_sentinels: list[Position] = []     # colas de sentinels por poner
        self.refuerzo_dirs: list[Direction] = []         # dirección de cada sentinel
        self.fase_previa: int = 2                        # a qué fase volver tras refuerzo

        # Torreta enemiga que disparó la fase de refuerzo
        self.threat_dir: Direction | None = None

        # ── Conveyors que necesitan reparación (visibles, fase 0) ─────────
        self._repair_cooldown: int = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de posición
    # ─────────────────────────────────────────────────────────────────────────

    def _in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not self._in_bounds(dest):
            return False
        if c.can_move(direction):
            c.move(direction)
            return True
        return False

    def _move_toward(self, c: Controller, target: Position) -> bool:
        """Mueve hacia target usando el navegador, construyendo road en el camino."""
        current = c.get_position()
        direction = self.navegador.moveTo(c, target, four_dirs=False)
        next_pos = current.add(direction)
        if self._in_bounds(next_pos) and c.can_build_road(next_pos):
            c.build_road(next_pos)
        return self._try_move(c, direction)

    # ─────────────────────────────────────────────────────────────────────────
    # Detección del splitter de defensivo
    # ─────────────────────────────────────────────────────────────────────────

    def _find_friendly_splitter(self, c: Controller) -> Position | None:
        """Busca un splitter aliado dentro del radio de visión."""
        for b in c.get_nearby_buildings():
            if (c.get_entity_type(b) == EntityType.SPLITTER
                    and c.get_team(b) == c.get_team()):
                return c.get_position(b)
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Detección de amenazas en visión
    # ─────────────────────────────────────────────────────────────────────────

    def _find_enemy_turret(self, c: Controller) -> tuple[Position, Direction] | None:
        """
        Devuelve (pos_torreta, dirección_desde_chain_head_hacia_torreta) si hay
        alguna torreta enemiga en visión. None si no hay.
        """
        for b in c.get_nearby_buildings():
            if c.get_team(b) == c.get_team():
                continue
            typ = c.get_entity_type(b)
            if typ in (EntityType.GUNNER, EntityType.SENTINEL,
                       EntityType.BREACH, EntityType.LAUNCHER):
                pos = c.get_position(b)
                if self.chain_head is not None:
                    d = self.chain_head.direction_to(pos)
                else:
                    d = c.get_position().direction_to(pos)
                return pos, d
        return None

    def _find_enemy_core(self, c: Controller) -> Position | None:
        """Devuelve la posición del core enemigo si está en visión."""
        for b in c.get_nearby_buildings():
            if (c.get_entity_type(b) == EntityType.CORE
                    and c.get_team(b) != c.get_team()):
                return c.get_position(b)
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Fase 0 – ESPERA en base
    # ─────────────────────────────────────────────────────────────────────────

    def _fase_espera(self, c: Controller):
        current = c.get_position()
        c.draw_indicator_dot(current, 128, 128, 128)

        # Curar si podemos
        if self.my_core is not None and c.can_heal(self.my_core):
            c.heal(self.my_core)

        # Curar cualquier aliado dañado en rango
        for b in c.get_nearby_buildings():
            pos = c.get_position(b)
            if c.get_team(b) == c.get_team():
                if c.get_hp(b) < c.get_max_hp(b) and c.can_heal(pos):
                    c.heal(pos)
                    break  # una curación por turno

        # Reparar conveyors rotos: destruirlos y reconstruirlos
        for b in c.get_nearby_buildings():
            if c.get_team(b) != c.get_team():
                continue
            typ = c.get_entity_type(b)
            if typ not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                continue
            pos = c.get_position(b)
            if c.get_hp(b) < c.get_max_hp(b) and c.can_heal(pos):
                c.heal(pos)
                break

        # Detectar splitter → transición a fase 1/2
        spl = self._find_friendly_splitter(c)
        if spl is not None:
            self.splitter_pos = spl
            self.fase = 1

    # ─────────────────────────────────────────────────────────────────────────
    # Fase 1 – BUSCAR_SPLITTER y calcular origen de cadena
    # ─────────────────────────────────────────────────────────────────────────

    def _fase_buscar_splitter(self, c: Controller):
        current = c.get_position()
        c.draw_indicator_dot(current, 200, 200, 50)

        # Intentar localizar el splitter si aún no lo tenemos
        spl = self._find_friendly_splitter(c)
        if spl is not None:
            self.splitter_pos = spl

        if self.splitter_pos is None:
            # Volver a esperar
            self.fase = 0
            return

        spl = self.splitter_pos

        # Calcular dirección hacia el core enemigo (o estimado) desde el splitter
        enemy_target = self._get_enemy_target()
        if enemy_target is None:
            # Sin objetivo enemigo todavía, volver a esperar
            self.fase = 0
            return

        # Dirección de avance: desde el splitter hacia el core enemigo
        advance_dir = spl.direction_to(enemy_target)
        # Preferir dirección cardinal
        if _is_diagonal(advance_dir):
            # Elegir el cardinal más cercano al diagonal
            dx, dy = advance_dir.delta()
            if abs(enemy_target.x - spl.x) >= abs(enemy_target.y - spl.y):
                advance_dir = Direction.EAST if dx > 0 else Direction.WEST
            else:
                advance_dir = Direction.SOUTH if dy > 0 else Direction.NORTH

        self.advance_dir = advance_dir

        # La cabeza inicial de la cadena es la casilla adyacente al splitter
        # en la dirección de avance.
        chain_start = spl.add(advance_dir)
        if not self._in_bounds(chain_start):
            self.fase = 0
            return

        self.chain_head = chain_start
        self.fase = 2

    def _get_enemy_target(self) -> Position | None:
        """Devuelve el objetivo enemigo conocido o la mejor estimación."""
        if self.enemy_core_pos is not None:
            return self.enemy_core_pos
        if self.enemy_core_candidates:
            return self.enemy_core_candidates[self.symmetry_idx % len(self.enemy_core_candidates)]
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Fase 2 – CADENA de conveyors
    # ─────────────────────────────────────────────────────────────────────────

    def _fase_cadena(self, c: Controller):
        current = c.get_position()
        c.draw_indicator_dot(current, 50, 200, 50)

        # Actualizar posición del core enemigo si lo vemos
        enemy_core = self._find_enemy_core(c)
        if enemy_core is not None:
            self.enemy_core_pos = enemy_core

        # ¿Vemos el core enemigo? → fase 4
        if self.enemy_core_pos is not None and c.is_in_vision(self.enemy_core_pos):
            self._iniciar_asalto_final(c)
            return

        # ¿Vemos una torreta enemiga? → fase 3 (refuerzo)
        threat = self._find_enemy_turret(c)
        if threat is not None:
            _, threat_dir = threat
            self.threat_dir = threat_dir
            self._iniciar_refuerzo(c, final=False)
            return

        # ¿También buscamos el core si aún no lo sabemos?
        if self.enemy_core_pos is None:
            self._buscar_core_en_vision(c)

        # chain_head debe estar definido
        if self.chain_head is None or self.advance_dir is None:
            self.fase = 1
            return

        head = self.chain_head

        # ── Ir a la casilla head ────────────────────────────────────────────
        if current.distance_squared(head) > 2:
            self._move_toward(c, head)
            return

        # ── Construir el conveyor en head ───────────────────────────────────
        # El conveyor apunta en advance_dir (lleva recursos hacia adelante).
        if not c.is_in_vision(head):
            self._move_toward(c, head)
            return

        building_at_head = c.get_tile_building_id(head)

        if building_at_head is not None:
            typ = c.get_entity_type(building_at_head)
            team = c.get_team(building_at_head)

            if typ == EntityType.CONVEYOR and team == c.get_team():
                # Ya hay conveyor aliado → avanzar head
                self._advance_head()
                return

            if team == c.get_team():
                # Otro edificio aliado: no destruir, simplemente rodear
                self._rodear_obstaculo(c, head)
                return

            # Edificio enemigo en head: destruir si podemos pararnos encima
            self._limpiar_casilla_enemiga(c, head)
            return

        env = c.get_tile_env(head)
        if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            # No podemos construir aquí: rodear
            self._rodear_obstaculo(c, head)
            return

        # Casilla vacía y en rango: construir conveyor
        if current == head:
            # Salir un paso para poder construir
            back_dir = self.advance_dir.opposite()
            self._try_move(c, back_dir)
            return

        if c.can_build_conveyor(head, self.advance_dir):
            c.build_conveyor(head, self.advance_dir)
            self.conveyors_built += 1
            self._advance_head()
        else:
            # Sin recursos o cooldown: esperar
            pass

    def _advance_head(self):
        """Mueve la cabeza de la cadena un paso en advance_dir."""
        if self.chain_head is not None and self.advance_dir is not None:
            self.chain_head = self.chain_head.add(self.advance_dir)

    def _rodear_obstaculo(self, c: Controller, blocked: Position):
        """
        Si hay un obstáculo en la dirección de avance, intentamos girar
        90° y continuar. Actualiza advance_dir si es necesario.
        """
        current = c.get_position()
        # Intentar girar a derecha o izquierda
        for turn in (self.advance_dir.rotate_right(), self.advance_dir.rotate_left()):
            candidate = blocked.add(turn)  # casilla al lado del obstáculo, hacia adelante
            # En realidad giramos desde current
            candidate2 = current.add(turn)
            if (self._in_bounds(candidate2)
                    and c.is_in_vision(candidate2)
                    and c.get_tile_env(candidate2) not in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)
                    and c.get_tile_building_id(candidate2) is None):
                self.advance_dir = turn
                self.chain_head = candidate2
                return
        # Si no hay salida, simplemente intentar avanzar hacia el objetivo
        enemy = self._get_enemy_target()
        if enemy is not None:
            self._move_toward(c, enemy)

    def _limpiar_casilla_enemiga(self, c: Controller, target: Position):
        """Intenta colocarse encima de un edificio enemigo y atacarlo."""
        current = c.get_position()
        if current == target:
            if c.can_fire(target):
                c.fire(target)
        else:
            if c.is_tile_passable(target):
                self._move_toward(c, target)

    def _buscar_core_en_vision(self, c: Controller):
        """Revisa si alguno de los candidatos del core enemigo ya está en visión."""
        for candidate in self.enemy_core_candidates:
            if c.is_in_vision(candidate):
                bid = c.get_tile_building_id(candidate)
                if bid is not None and c.get_entity_type(bid) == EntityType.CORE and c.get_team(bid) != c.get_team():
                    self.enemy_core_pos = candidate
                    return
                elif c.is_in_vision(candidate):
                    # Este candidato no era correcto: marcar y probar el siguiente
                    pass

    # ─────────────────────────────────────────────────────────────────────────
    # Fase 3 – REFUERZO (splitter + 2 sentinels por amenaza)
    # ─────────────────────────────────────────────────────────────────────────

    def _iniciar_refuerzo(self, c: Controller, final: bool):
        """
        Prepara la construcción de un splitter en chain_head y los sentinels.
        Si final=True (core enemigo visible), pone 3 sentinels en vez de 2.
        """
        head = self.chain_head
        if head is None:
            return

        self.refuerzo_pos = head
        self.refuerzo_sentinels = []
        self.refuerzo_dirs = []

        adv = self.advance_dir
        if adv is None:
            return

        # Lados perpendiculares al avance
        left_dir = adv.rotate_left()
        right_dir = adv.rotate_right()

        left_pos = head.add(left_dir)
        right_pos = head.add(right_dir)
        front_pos = head.add(adv)

        # Dirección a la que apuntarán los sentinels: hacia donde vimos la amenaza
        threat = self.threat_dir if self.threat_dir is not None else adv

        if self._in_bounds(left_pos):
            self.refuerzo_sentinels.append(left_pos)
            self.refuerzo_dirs.append(threat)
        if self._in_bounds(right_pos):
            self.refuerzo_sentinels.append(right_pos)
            self.refuerzo_dirs.append(threat)
        if final and self._in_bounds(front_pos):
            # Tercer sentinel justo enfrente del splitter, apuntando al core enemigo
            self.refuerzo_sentinels.append(front_pos)
            self.refuerzo_dirs.append(adv)

        self.fase_previa = 4 if final else 2
        self.fase = 3

    def _iniciar_asalto_final(self, c: Controller):
        """Prepara refuerzo final con 3 sentinels al ver el core enemigo."""
        self._iniciar_refuerzo(c, final=True)

    def _fase_refuerzo(self, c: Controller):
        current = c.get_position()
        c.draw_indicator_dot(current, 255, 100, 0)

        refuerzo = self.refuerzo_pos
        if refuerzo is None:
            self._terminar_refuerzo(c)
            return

        # ── Paso 1: Construir splitter en refuerzo_pos ──────────────────────
        if c.is_in_vision(refuerzo):
            building = c.get_tile_building_id(refuerzo)
            splitter_ok = (
                building is not None
                and c.get_entity_type(building) == EntityType.SPLITTER
                and c.get_team(building) == c.get_team()
            )
            if not splitter_ok:
                # Limpiar si hay algo
                if building is not None:
                    if c.get_team(building) == c.get_team() and c.can_destroy(refuerzo):
                        c.destroy(refuerzo)
                        return
                    elif c.get_team(building) != c.get_team():
                        self._limpiar_casilla_enemiga(c, refuerzo)
                        return

                # Construir: acercarse si hace falta
                if current == refuerzo:
                    back = self.advance_dir.opposite() if self.advance_dir else Direction.SOUTH
                    self._try_move(c, back)
                    return

                if current.distance_squared(refuerzo) > 2:
                    self._move_toward(c, refuerzo)
                    return

                # La dirección del splitter: hacia adelante (hacia el enemigo)
                spl_dir = self.advance_dir if self.advance_dir else Direction.NORTH
                if c.can_build_splitter(refuerzo, spl_dir):
                    c.build_splitter(refuerzo, spl_dir)
                else:
                    # Sin recursos: esperar
                    return
        else:
            self._move_toward(c, refuerzo)
            return

        # ── Paso 2: Construir sentinels pendientes ───────────────────────────
        while self.refuerzo_sentinels:
            s_pos = self.refuerzo_sentinels[0]
            s_dir = self.refuerzo_dirs[0]

            if not self._in_bounds(s_pos):
                self.refuerzo_sentinels.pop(0)
                self.refuerzo_dirs.pop(0)
                continue

            if not c.is_in_vision(s_pos):
                self._move_toward(c, s_pos)
                return

            building = c.get_tile_building_id(s_pos)
            sentinel_ok = (
                building is not None
                and c.get_entity_type(building) == EntityType.SENTINEL
                and c.get_team(building) == c.get_team()
            )
            if sentinel_ok:
                self.refuerzo_sentinels.pop(0)
                self.refuerzo_dirs.pop(0)
                continue

            # Limpiar si hay algo
            if building is not None:
                if c.get_team(building) == c.get_team() and c.can_destroy(s_pos):
                    c.destroy(s_pos)
                    return
                elif c.get_team(building) != c.get_team():
                    self._limpiar_casilla_enemiga(c, s_pos)
                    return

            env = c.get_tile_env(s_pos)
            if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                # No se puede construir aquí: skip
                self.refuerzo_sentinels.pop(0)
                self.refuerzo_dirs.pop(0)
                continue

            # Acercarse si hace falta
            if current == s_pos:
                back = self.advance_dir.opposite() if self.advance_dir else Direction.SOUTH
                self._try_move(c, back)
                return

            if current.distance_squared(s_pos) > 2:
                self._move_toward(c, s_pos)
                return

            if c.can_build_sentinel(s_pos, s_dir):
                c.build_sentinel(s_pos, s_dir)
                self.refuerzo_sentinels.pop(0)
                self.refuerzo_dirs.pop(0)
            else:
                # Sin recursos: esperar
                return

        # ── Todos los sentinels construidos ─────────────────────────────────
        self._terminar_refuerzo(c)

    def _terminar_refuerzo(self, c: Controller):
        """Una vez terminado el refuerzo, continúa la cadena o termina."""
        if self.fase_previa == 4:
            # Asalto final completado — el bot ya no tiene más que hacer
            self.fase = 4
            return

        # Continuar la cadena: avanzar la head más allá del splitter de refuerzo
        if self.refuerzo_pos is not None and self.advance_dir is not None:
            # La chain_head queda un paso más allá del splitter
            self.chain_head = self.refuerzo_pos.add(self.advance_dir)

        self.threat_dir = None
        self.refuerzo_pos = None
        self.fase = 2

    # ─────────────────────────────────────────────────────────────────────────
    # Fase 4 – ASALTO FINAL completado
    # ─────────────────────────────────────────────────────────────────────────

    def _fase_final(self, c: Controller):
        current = c.get_position()
        c.draw_indicator_dot(current, 255, 0, 0)
        # El bot queda quieto curando lo que pueda
        if self.my_core is not None and c.can_heal(self.my_core):
            c.heal(self.my_core)
        for b in c.get_nearby_buildings():
            pos = c.get_position(b)
            if c.get_team(b) == c.get_team() and c.get_hp(b) < c.get_max_hp(b):
                if c.can_heal(pos):
                    c.heal(pos)
                    break

    # ─────────────────────────────────────────────────────────────────────────
    # Punto de entrada principal
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, c: Controller):
        # Actualizar referencia al core propio si aún no la tenemos
        if self.my_core is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) == c.get_team():
                    self.my_core = c.get_position(b)
                    break

        # Actualizar candidatos del core enemigo si el mapa cambió de tamaño
        # (no debería ocurrir, pero por seguridad)
        if not self.enemy_core_candidates and self.my_core is not None:
            x, y = self.my_core.x, self.my_core.y
            w, h = self.map_w, self.map_h
            self.enemy_core_candidates = [
                Position(w - 1 - x, y),
                Position(x, h - 1 - y),
                Position(w - 1 - x, h - 1 - y),
            ]

        # Comprobar siempre si vemos el splitter aliado para hacer la transición
        if self.fase == 0:
            spl = self._find_friendly_splitter(c)
            if spl is not None:
                self.splitter_pos = spl
                self.fase = 1

        # Despachar según la fase actual
        if self.fase == 0:
            self._fase_espera(c)
        elif self.fase == 1:
            self._fase_buscar_splitter(c)
        elif self.fase == 2:
            self._fase_cadena(c)
        elif self.fase == 3:
            self._fase_refuerzo(c)
        elif self.fase == 4:
            self._fase_final(c)