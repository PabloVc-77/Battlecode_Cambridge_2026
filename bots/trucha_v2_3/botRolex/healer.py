from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav
from botRolex.helper.layout_defensivo import compute_layout_for_core

HEAL_PRIORITY: dict[EntityType, int] = {
    EntityType.CORE:               0,
    EntityType.BRIDGE:             1,
    EntityType.SPLITTER:           1,
    EntityType.CONVEYOR:           1,
    EntityType.FOUNDRY:            2,
    EntityType.ARMOURED_CONVEYOR:  2,
    EntityType.LAUNCHER:           3,
    EntityType.SENTINEL:           4,
    EntityType.GUNNER:             5,
    EntityType.BREACH:             6,
    EntityType.HARVESTER:          7,
    EntityType.BARRIER:            8,
    EntityType.ROAD:               9,
}

TRACKED_TYPES: frozenset[EntityType] = frozenset({
    EntityType.CORE, EntityType.FOUNDRY, EntityType.HARVESTER,
    EntityType.LAUNCHER, EntityType.ARMOURED_CONVEYOR, EntityType.SENTINEL,
    EntityType.GUNNER, EntityType.BREACH, EntityType.BRIDGE,
    EntityType.SPLITTER, EntityType.CONVEYOR, EntityType.BARRIER,
})

TRANSPORT_TYPES: frozenset[EntityType] = frozenset({
    EntityType.BRIDGE, EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER,
})

ENEMY_TURRET_TYPES: frozenset[EntityType] = frozenset({
    EntityType.SENTINEL, EntityType.GUNNER, EntityType.BREACH,
})

MARKER_BROKEN_CHAIN = 0xDEAD


class Healer:
    def __init__(self, c: Controller):
        self.navegador = bugnav.BugNav()
        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()

        self.core_pos = None
        self.end_bridges = []
        self._eb_index = 0

        self.patrol_route = []
        self.going_forward = True
        self.patrol_index = 0

        # P1: counter turret (máxima prioridad)
        # (estado gestionado por _run_counter_turret, vars debajo)

        # P2: intercept enemy bot via splitter + sentinel
        self._intercept_enemy_pos = None    # última pos vista del bot enemigo
        self._intercept_splitter_pos = None # conveyor a convertir en splitter
        self._intercept_splitter_dir = None # dirección del conveyor original
        self._intercept_sentinel_pos = None # casilla donde poner el sentinel
        self._intercept_sentinel_dir = None # dirección hacia el bot enemigo

        # P2 (antiguo nombre, ahora P1): counter turret
        self._counter_target_pos = None
        self._counter_dir = None
        self._counter_enemy_turret = None

        # P3: broken chain
        self._broken_chain_reported = set()

        # Layout defensivo: posiciones reservadas donde no construir splitter/sentinel
        self.layout_positions: set[Position] = set()

        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_entity_type(b) == EntityType.CORE and c.get_team() == c.get_team(b):
                self.core_pos = c.get_position(b)
                break

        if self.core_pos is not None:
            try:
                result = compute_layout_for_core(c, self.core_pos)
                self.layout_positions = set(result.get('layout_positions', []))
            except Exception:
                self.layout_positions = set()

            s = self.core_pos
            candidates = [
                s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.EAST),
                s.add(Direction.NORTH).add(Direction.NORTH),
                s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.WEST),
                s.add(Direction.EAST).add(Direction.EAST).add(Direction.NORTH),
                s.add(Direction.EAST).add(Direction.EAST),
                s.add(Direction.EAST).add(Direction.EAST).add(Direction.SOUTH),
                s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.EAST),
                s.add(Direction.SOUTH).add(Direction.SOUTH),
                s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.WEST),
                s.add(Direction.WEST).add(Direction.WEST).add(Direction.NORTH),
                s.add(Direction.WEST).add(Direction.WEST),
                s.add(Direction.WEST).add(Direction.WEST).add(Direction.SOUTH),
            ]
            for v in candidates:
                if self._in_bounds(v) and c.get_tile_env(v) != Environment.WALL:
                    self.end_bridges.append(v)

    def _in_bounds(self, pos):
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    def _try_move(self, c, direction):
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not self._in_bounds(dest):
            return False
        if c.can_move(direction):
            c.move(direction)
            return True
        return False

    def _get_damaged_targets(self, c):
        current = c.get_position()
        damaged = []
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRACKED_TYPES:
                continue
            if c.get_hp(bid) < c.get_max_hp(bid):
                pos = c.get_position(bid)
                prio = HEAL_PRIORITY.get(etype, 99)
                dist = current.distance_squared(pos)
                damaged.append((prio, dist, pos))
        damaged.sort(key=lambda x: (x[0], x[1]))
        return damaged

    def _find_next_in_chain(self, c, target_pos, include_enemies):
        for bid in c.get_nearby_buildings():
            if not include_enemies and c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES:
                continue
            pos = c.get_position(bid)
            if pos == target_pos:
                continue
            if etype == EntityType.BRIDGE:
                try:
                    out = c.get_bridge_target(bid)
                except Exception:
                    continue
                if out == target_pos:
                    return pos
            elif etype == EntityType.SPLITTER:
                try:
                    out = c.get_direction(bid)
                except Exception:
                    continue
                if pos.add(out) == target_pos:
                    return pos
                if pos.add(out.rotate_left().rotate_left()) == target_pos:
                    return pos
                if pos.add(out.rotate_right().rotate_right()) == target_pos:
                    return pos
            else:
                try:
                    d = c.get_direction(bid)
                except Exception:
                    continue
                if pos.add(d) == target_pos:
                    return pos
        return None

    def _enemy_turret_still_alive(self, c, turret_pos):
        if not c.is_in_vision(turret_pos):
            return True
        bid = c.get_tile_building_id(turret_pos)
        if bid is None:
            return False
        return c.get_entity_type(bid) in ENEMY_TURRET_TYPES and c.get_team(bid) != c.get_team()

    def _counter_sentinel_done(self, c):
        if self._counter_target_pos is None:
            return True
        if not c.is_in_vision(self._counter_target_pos):
            return False
        bid = c.get_tile_building_id(self._counter_target_pos)
        if bid is None:
            return False
        return c.get_entity_type(bid) == EntityType.SENTINEL and c.get_team(bid) == c.get_team()

    def _get_enemy_turrets(self, c, builds):
        result = []
        for bid in builds:
            if c.get_team(bid) == c.get_team():
                continue
            if c.get_entity_type(bid) in ENEMY_TURRET_TYPES:
                result.append(c.get_position(bid))
        return result

    def _has_allied_healer_nearby(self, c, target_pos):
        my_id = c.get_id()
        for uid in c.get_nearby_units():
            if uid == my_id:
                continue
            if c.get_team(uid) != c.get_team():
                continue
            if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            if c.get_position(uid).distance_squared(target_pos) <= 2:
                return True
        return False

    # ── P2 helpers: intercept enemy bot (splitter + sentinel) ───────────────

    def _get_nearby_enemy_bots(self, c):
        """Devuelve lista de (dist², pos) de bots enemigos en visión, ordenada."""
        current = c.get_position()
        result = []
        for uid in c.get_nearby_units():
            if c.get_team(uid) == c.get_team():
                continue
            if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            pos = c.get_position(uid)
            result.append((current.distance_squared(pos), pos))
        result.sort()
        return result

    def _enemy_bot_still_present(self, c, enemy_pos):
        """True si hay un bot enemigo en enemy_pos o en alguna casilla adyacente visible."""
        if not c.is_in_vision(enemy_pos):
            return False
        uid = c.get_tile_builder_bot_id(enemy_pos)
        if uid is not None and c.get_team(uid) != c.get_team():
            return True
        for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
                  Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST]:
            adj = enemy_pos.add(d)
            if not self._in_bounds(adj) or not c.is_in_vision(adj):
                continue
            uid2 = c.get_tile_builder_bot_id(adj)
            if uid2 is not None and c.get_team(uid2) != c.get_team():
                return True
        return False

    def _find_best_conveyor_for_intercept(self, c, enemy_pos):
        """
        Busca el conveyor/armoured_conveyor aliado más cercano a enemy_pos
        que no esté en el layout defensivo.

        Devuelve (conv_pos, splitter_dir, feeder_is_bridge) donde:
          - conv_pos: posición del conveyor a reemplazar
          - splitter_dir: dirección en la que debe apuntar el splitter,
            calculada mirando quién alimenta al conveyor:
              · Si el feeder es otro conveyor/armoured_conveyor aliado,
                el splitter apunta en la misma dirección que ese feeder
                (así la fuente queda "detrás" del splitter).
              · Si el feeder es un bridge o no se encuentra, se mantiene
                la dirección original del conveyor.
          - feeder_is_bridge: True si la fuente detectada es un bridge

        Prioridad: conveyors con recurso almacenado > conveyors vacíos.
        Devuelve None si no hay candidatos válidos.
        """
        best_with_resource = None
        best_with_resource_dist = 10**9
        best_empty = None
        best_empty_dist = 10**9

        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                continue
            pos = c.get_position(bid)

            # No construir en posiciones del layout defensivo
            if pos in self.layout_positions:
                continue

            try:
                conv_dir = c.get_direction(bid)
            except Exception:
                continue

            dist = pos.distance_squared(enemy_pos)

            # Determinar la dirección correcta del splitter consultando el feeder
            splitter_dir, feeder_is_bridge = self._get_splitter_dir_from_feeder(
                c, pos, conv_dir
            )

            has_resource = c.get_stored_resource(bid) is not None
            entry = (pos, splitter_dir, feeder_is_bridge)
            if has_resource:
                if dist < best_with_resource_dist:
                    best_with_resource_dist = dist
                    best_with_resource = entry
            else:
                if dist < best_empty_dist:
                    best_empty_dist = dist
                    best_empty = entry

        return best_with_resource if best_with_resource is not None else best_empty

    def _get_splitter_dir_from_feeder(self, c, conv_pos, conv_dir):
        """
        Dado un conveyor en conv_pos con dirección conv_dir, busca quién lo
        alimenta (el edificio cuyo output apunta a conv_pos) y devuelve
        (splitter_dir, feeder_is_bridge):

          - Si el feeder es un conveyor/armoured_conveyor aliado:
              splitter_dir = dirección de ese feeder
              (el splitter hereda la dirección de su alimentador, así la
               fuente queda en la entrada trasera del splitter)
          - Si el feeder es un bridge aliado, o no se encuentra feeder:
              splitter_dir = conv_dir  (mantener dirección original)
              feeder_is_bridge = True si era bridge, False si no había feeder
        """
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES:
                continue
            pos = c.get_position(bid)
            if pos == conv_pos:
                continue

            # Comprobar si este edificio apunta a conv_pos
            if etype == EntityType.BRIDGE:
                try:
                    target = c.get_bridge_target(bid)
                except Exception:
                    continue
                if target == conv_pos:
                    # Feeder es un bridge: mantener dirección original
                    return conv_dir, True
            elif etype == EntityType.SPLITTER:
                try:
                    d = c.get_direction(bid)
                except Exception:
                    continue
                if (pos.add(d) == conv_pos
                        or pos.add(d.rotate_left().rotate_left()) == conv_pos
                        or pos.add(d.rotate_right().rotate_right()) == conv_pos):
                    # Feeder es un splitter: mantener dirección original (caso raro)
                    return conv_dir, False
            else:  # CONVEYOR, ARMOURED_CONVEYOR
                try:
                    d = c.get_direction(bid)
                except Exception:
                    continue
                if pos.add(d) == conv_pos:
                    # Feeder es un conveyor: el splitter apunta igual que el feeder
                    return d, False

        # No se encontró feeder visible: mantener dirección original
        return conv_dir, False

    def _find_sentinel_spot_for_splitter(self, c, splitter_pos, splitter_dir, enemy_pos):
        """
        Busca una casilla a izquierda o derecha del splitter (90° del eje
        de transporte) donde colocar el sentinel.

        Reglas de exclusión (además de paredes/ores/fuera de visión):
          - No usar casillas del layout defensivo
          - No usar casillas que contengan conveyor, armoured_conveyor o bridge
            aliados (no queremos romper nuestra propia cadena)

        Si ya existe un sentinel aliado en uno de esos lados (válido), lo reutiliza.
        Devuelve (pos, dir_to_enemy) o (None, None).
        """
        left_dir  = splitter_dir.rotate_left().rotate_left()   # 90° CCW
        right_dir = splitter_dir.rotate_right().rotate_right()  # 90° CW
        front_dir = splitter_dir

        for side_dir in (left_dir, right_dir, front_dir):
            candidate = splitter_pos.add(side_dir)
            if not self._in_bounds(candidate) or not c.is_in_vision(candidate):
                continue
            if candidate in self.layout_positions:
                continue
            env = c.get_tile_env(candidate)
            if env == Environment.WALL:
                continue
            bid = c.get_tile_building_id(candidate)
            if bid is not None:
                etype = c.get_entity_type(bid)
                team = c.get_team(bid)
                # Reutilizar sentinel aliado existente
                if etype == EntityType.SENTINEL and team == c.get_team():
                    return candidate, candidate.direction_to(enemy_pos)
                # No ocupar casillas de transporte aliado
                if team == c.get_team() and etype in (
                    EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE
                ):
                    continue
                # Cualquier otro edificio ocupa la casilla
                if not c.is_tile_empty(candidate):
                    continue
            return candidate, candidate.direction_to(enemy_pos)

        return None, None

    def _intercept_setup(self, c, enemy_pos):
        """
        Dado un bot enemigo en enemy_pos, calcula y guarda los objetivos
        de splitter y sentinel. Devuelve True si se pudo calcular todo.
        """
        result = self._find_best_conveyor_for_intercept(c, enemy_pos)
        if result is None:
            return False
        splitter_pos, splitter_dir, _feeder_is_bridge = result

        sentinel_pos, sentinel_dir = self._find_sentinel_spot_for_splitter(
            c, splitter_pos, splitter_dir, enemy_pos
        )

        self._intercept_enemy_pos = enemy_pos
        self._intercept_splitter_pos = splitter_pos
        self._intercept_splitter_dir = splitter_dir
        self._intercept_sentinel_pos = sentinel_pos
        self._intercept_sentinel_dir = sentinel_dir
        return True

    def _intercept_clear(self):
        self._intercept_enemy_pos = None
        self._intercept_splitter_pos = None
        self._intercept_splitter_dir = None
        self._intercept_sentinel_pos = None
        self._intercept_sentinel_dir = None

    def _run_intercept(self, c):
        """
        P2: interceptar bot enemigo.
        Estrategia:
          1. Convertir el conveyor aliado más cercano al bot en un splitter
             (misma dirección). El splitter redirigirá recursos al sentinel.
          2. Colocar un sentinel a izquierda o derecha del splitter apuntando
             a la última posición vista del bot.
        El objetivo es persistente: no se limpia hasta que el bot desaparezca
        de visión o se complete la instalación.
        Devuelve True si hay trabajo activo.
        """
        # Verificar si el objetivo activo sigue siendo válido
        if self._intercept_enemy_pos is not None:
            if not self._enemy_bot_still_present(c, self._intercept_enemy_pos):
                self._intercept_clear()
            else:
                # Actualizar dirección del sentinel hacia la posición actual del bot
                nearby_bots = self._get_nearby_enemy_bots(c)
                if nearby_bots:
                    _, current_enemy_pos = nearby_bots[0]
                    self._intercept_enemy_pos = current_enemy_pos
                    if self._intercept_sentinel_pos is not None:
                        self._intercept_sentinel_dir = self._intercept_sentinel_pos.direction_to(current_enemy_pos)

        # Sin objetivo: buscar uno nuevo
        if self._intercept_enemy_pos is None:
            nearby_bots = self._get_nearby_enemy_bots(c)
            if not nearby_bots:
                return False
            _, enemy_pos = nearby_bots[0]
            if not self._intercept_setup(c, enemy_pos):
                return False

        current = c.get_position()

        # ── Paso 1: splitter ──────────────────────────────────────────────────
        splitter_done = False
        if self._intercept_splitter_pos is not None:
            c.draw_indicator_dot(self._intercept_splitter_pos, 255, 140, 0)
            bid = c.get_tile_building_id(self._intercept_splitter_pos)
            if (bid is not None
                    and c.get_entity_type(bid) == EntityType.SPLITTER
                    and c.get_team(bid) == c.get_team()):
                splitter_done = True
            else:
                # Destruir el conveyor existente y construir splitter
                if bid is not None and c.get_team(bid) == c.get_team():
                    # Acercarse si hace falta para poder destruir
                    if current.distance_squared(self._intercept_splitter_pos) > 2:
                        d = self.navegador.moveTo(c, self._intercept_splitter_pos, four_dirs=False)
                        nxt = current.add(d)
                        if c.can_build_road(nxt):
                            c.build_road(nxt)
                        self._try_move(c, d)
                        return True
                    if c.can_destroy(self._intercept_splitter_pos):
                        c.destroy(self._intercept_splitter_pos)
                    return True  # El siguiente turno la casilla estará vacía
                # Casilla vacía: construir splitter
                splitter_done = self.construir_splitter(
                    c, self._intercept_splitter_pos, self._intercept_splitter_dir
                )

        # ── Paso 2: sentinel ──────────────────────────────────────────────────
        if self._intercept_sentinel_pos is not None and self._intercept_sentinel_dir is not None:
            c.draw_indicator_dot(self._intercept_sentinel_pos, 255, 0, 0)
            bid = c.get_tile_building_id(self._intercept_sentinel_pos)
            sentinel_done = (
                bid is not None
                and c.get_entity_type(bid) == EntityType.SENTINEL
                and c.get_team(bid) == c.get_team()
            )
            if not sentinel_done:
                self.construir(
                    c, self._intercept_sentinel_pos,
                    EntityType.SENTINEL, self._intercept_sentinel_dir
                )

        return True

    def construir_splitter(self, c, objetivo, direccion):
        """
        Igual que construir() pero para splitters. Devuelve True cuando
        hay un splitter aliado con la dirección correcta en objetivo.
        """
        current = c.get_position()
        bid = c.get_tile_building_id(objetivo)
        if bid is not None:
            etype = c.get_entity_type(bid)
            team = c.get_team(bid)
            if etype == EntityType.SPLITTER and team == c.get_team():
                return True
            # Cualquier otro edificio: no podemos construir aquí
            return False
        if current.distance_squared(objetivo) > 2:
            d = self.navegador.moveTo(c, objetivo, four_dirs=False)
            nxt = current.add(d)
            if c.can_build_road(nxt):
                c.build_road(nxt)
            self._try_move(c, d)
            return False
        if current == objetivo:
            d = self.navegador.moveTo(c, self.core_pos, four_dirs=False)
            nxt = current.add(d)
            if c.can_build_road(nxt):
                c.build_road(nxt)
            self._try_move(c, d)
            return False
        if c.can_build_splitter(objetivo, direccion):
            c.build_splitter(objetivo, direccion)
            return True
        return False

    # ── P2 helpers ──────────────────────────────────────────────────────────

    def _update_counter_target(self, c, builds):
        current = c.get_position()
        enemy_turrets = self._get_enemy_turrets(c, builds)
        if not enemy_turrets:
            return
        enemy_turrets.sort(key=lambda pos: current.distance_squared(pos))
        for turret_pos in enemy_turrets:
            fuente = self._find_next_in_chain(c, turret_pos, include_enemies=True)
            if fuente is None:
                continue
            self._counter_target_pos = fuente
            self._counter_dir = fuente.direction_to(turret_pos)
            self._counter_enemy_turret = turret_pos
            return

    def _run_counter_turret(self, c, builds):
        current = c.get_position()
        if self._counter_target_pos is not None:
            if not self._enemy_turret_still_alive(c, self._counter_enemy_turret) or self._counter_sentinel_done(c):
                self._counter_target_pos = None
                self._counter_dir = None
                self._counter_enemy_turret = None
            else:
                c.draw_indicator_dot(self._counter_target_pos, 255, 0, 0)
                done = self.construir(c, self._counter_target_pos, EntityType.SENTINEL, self._counter_dir)
                if done:
                    self._counter_target_pos = None
                    self._counter_dir = None
                    self._counter_enemy_turret = None
                return True

        self._update_counter_target(c, builds)
        if self._counter_target_pos is not None:
            c.draw_indicator_dot(self._counter_target_pos, 255, 0, 0)
            done = self.construir(c, self._counter_target_pos, EntityType.SENTINEL, self._counter_dir)
            if done:
                self._counter_target_pos = None
                self._counter_dir = None
                self._counter_enemy_turret = None
            return True
        return False

    # ── P3: broken chain detection ───────────────────────────────────────────

    def _detect_broken_chain(self, c):
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES:
                continue
            pos = c.get_position(bid)
            dest = None
            if etype == EntityType.BRIDGE:
                try:
                    dest = c.get_bridge_target(bid)
                except Exception:
                    continue
            else:
                try:
                    dest = pos.add(c.get_direction(bid))
                except Exception:
                    continue
            if dest is None or dest in self.end_bridges:
                continue
            if not self._in_bounds(dest) or not c.is_in_vision(dest):
                continue
            env = c.get_tile_env(dest)
            if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                continue
            dest_bid = c.get_tile_building_id(dest)
            if dest_bid is not None:
                if c.get_team(dest_bid) == c.get_team() and c.get_entity_type(dest_bid) in TRANSPORT_TYPES:
                    self._broken_chain_reported.discard(dest)
                    continue
                if c.get_team(dest_bid) == c.get_team():
                    continue
            if c.can_place_marker(dest):
                c.place_marker(dest, MARKER_BROKEN_CHAIN)
                self._broken_chain_reported.add(dest)
            c.draw_indicator_dot(dest, 255, 128, 0)
            return

    # ── Patrulla ─────────────────────────────────────────────────────────────

    def _start_new_patrol(self, c):
        if not self.end_bridges:
            return
        n = len(self.end_bridges)
        for attempt in range(n):
            idx = (self._eb_index + attempt) % n
            eb = self.end_bridges[idx]
            if not c.is_in_vision(eb):
                continue
            bid = c.get_tile_building_id(eb)
            if bid is None or c.get_team(bid) != c.get_team():
                continue
            if c.get_entity_type(bid) not in TRANSPORT_TYPES:
                continue
            self._eb_index = (idx + 1) % n
            self.patrol_route = [eb]
            self.patrol_index = 0
            self.going_forward = True
            return
        self.patrol_route = []

    def _patrol_move(self, c):
        current = c.get_position()
        if not self.patrol_route:
            self._start_new_patrol(c)
            if not self.patrol_route:
                c.draw_indicator_dot(current, 128, 128, 128)
                return
        self.patrol_index = max(0, min(self.patrol_index, len(self.patrol_route) - 1))
        target = self.patrol_route[self.patrol_index]
        if current == target:
            if self.going_forward:
                next_pos = self._find_next_in_chain(c, target, include_enemies=False)
                if next_pos is not None and next_pos not in self.patrol_route:
                    self.patrol_route.append(next_pos)
                    self.patrol_index += 1
                    target = next_pos
                    bid = c.get_tile_building_id(next_pos)
                    if bid is not None and c.get_entity_type(bid) == EntityType.HARVESTER:
                        self.going_forward = False
                else:
                    self.going_forward = False
                    self.patrol_index -= 1
                    if self.patrol_index < 0:
                        self._start_new_patrol(c)
                        return
                    target = self.patrol_route[self.patrol_index]
            else:
                self.patrol_index -= 1
                if self.patrol_index < 0:
                    self._start_new_patrol(c)
                    return
                target = self.patrol_route[self.patrol_index]
        c.draw_indicator_dot(target, 0, 200, 255)
        c.draw_indicator_line(current, target, 0, 200, 255)
        siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
        if c.can_build_road(current.add(siguiente_dir)):
            c.build_road(current.add(siguiente_dir))
        self._try_move(c, siguiente_dir)

    # ── Construcción genérica ────────────────────────────────────────────────

    def construir(self, c, objetivo, edificio, direccion=Direction.CENTRE):
        current = c.get_position()
        building_id = c.get_tile_building_id(objetivo)
        if building_id is not None:
            entity = c.get_entity_type(building_id)
            team = c.get_team(building_id)
            if entity == edificio and team == c.get_team():
                return True
            if c.is_tile_passable(objetivo) and team == c.get_team():
                if current.distance_squared(objetivo) > 2:
                    if not self.navegador.is_reachable(c, objetivo):
                        return True
                    d = self.navegador.moveTo(c, objetivo, four_dirs=False)
                    nxt = current.add(d)
                    if c.can_build_road(nxt):
                        c.build_road(nxt)
                    self._try_move(c, d)
                    return False
                if c.can_destroy(objetivo):
                    c.destroy(objetivo)
                return False
            elif c.is_tile_passable(objetivo) and team != c.get_team():
                if current != objetivo:
                    d = self.navegador.moveTo(c, objetivo, four_dirs=False)
                    nxt = current.add(d)
                    if c.can_build_road(nxt):
                        c.build_road(nxt)
                    self._try_move(c, d)
                if c.can_fire(objetivo):
                    c.fire(objetivo)
                if c.get_tile_building_id(objetivo) is None:
                    for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
                              Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST]:
                        adj = objetivo.add(d)
                        if self._in_bounds(adj):
                            if c.can_build_road(adj):
                                c.build_road(adj)
                            if self._try_move(c, d):
                                break
                return False
            else:
                return True
        if current.distance_squared(objetivo) > 2:
            d = self.navegador.moveTo(c, objetivo, four_dirs=False)
            nxt = current.add(d)
            if c.can_build_road(nxt):
                c.build_road(nxt)
            self._try_move(c, d)
            return False
        if current == objetivo:
            d = self.navegador.moveTo(c, self.core_pos, four_dirs=False)
            nxt = current.add(d)
            if c.can_build_road(nxt):
                c.build_road(nxt)
            self._try_move(c, d)
            return False
        if edificio == EntityType.SENTINEL:
            if c.can_build_sentinel(objetivo, direccion):
                c.build_sentinel(objetivo, direccion)
                return True
        if edificio == EntityType.BARRIER:
            if c.can_build_barrier(objetivo):
                c.build_barrier(objetivo)
                return True
        return False

    # ── run ──────────────────────────────────────────────────────────────────

    def run(self, c):
        current = c.get_position()
        if c.get_hp() < c.get_max_hp() and c.can_heal(current):
            c.heal(current)
            c.draw_indicator_dot(current, 255, 50, 50)

        builds = c.get_nearby_buildings()

        # ── P1: torreta enemiga existente → sentinel sobre su fuente ─────────
        if self._run_counter_turret(c, builds):
            #self._detect_broken_chain(c)
            return

        # ── P2: bot enemigo en visión → splitter + sentinel ───────────────────
        if self._run_intercept(c):
            #self._detect_broken_chain(c)
            return

        # ── P3: detección de huecos en cadena (markers, sin movimiento) ───────
        #self._detect_broken_chain(c)

        # ── P4: curar edificios aliados dañados (sin filtro de cobertura) ─────
        damaged = self._get_damaged_targets(c)
        if damaged:
            target_pos = damaged[0][2]
            c.draw_indicator_dot(target_pos, 255, 80, 0)
            c.draw_indicator_line(current, target_pos, 255, 80, 0)
            if c.can_heal(target_pos):
                c.heal(target_pos)
                c.draw_indicator_dot(current, 0, 255, 80)
            else:
                if c.get_action_cooldown() == 0:
                    for _, _, alt_pos in damaged[1:]:
                        if current.distance_squared(alt_pos) <= 2 and c.can_heal(alt_pos):
                            c.heal(alt_pos)
                            break
                siguiente_dir = self.navegador.moveTo(c, target_pos, four_dirs=False)
                if c.can_build_road(current.add(siguiente_dir)):
                    c.build_road(current.add(siguiente_dir))
                self._try_move(c, siguiente_dir)
        else:
            # ── P5: patrullar ─────────────────────────────────────────────────
            c.draw_indicator_dot(current, 0, 200, 255)
            self._patrol_move(c)