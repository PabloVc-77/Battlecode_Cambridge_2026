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

        # P1: counter turret
        self._counter_target_pos = None
        self._counter_dir = None
        self._counter_enemy_turret = None

        # P2: intercept enemy bot via splitter + sentinel
        self._intercept_enemy_pos = None
        self._intercept_splitter_pos = None
        self._intercept_splitter_dir = None
        self._intercept_sentinel_pos = None
        self._intercept_sentinel_dir = None
        # "allied" | "enemy" | None  — tipo de road a destruir antes del sentinel
        self._intercept_sentinel_road = None

        # P3: broken chain
        self._broken_chain_reported = set()

        # Layout defensivo
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

    # =========================================================================
    # Helpers generales
    # =========================================================================

    def _in_bounds(self, pos: Position):
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    def _try_move(self, c: Controller, direction: Direction):
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not self._in_bounds(dest):
            return False
        if c.can_move(direction):
            c.move(direction)
            return True
        return False

    def _get_damaged_targets(self, c: Controller):
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

    def _find_next_in_chain(self, c: Controller, target_pos: Position, include_enemies: bool):
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

    def _enemy_turret_still_alive(self, c: Controller, turret_pos: Position):
        if not c.is_in_vision(turret_pos):
            return True
        bid = c.get_tile_building_id(turret_pos)
        if bid is None:
            return False
        return c.get_entity_type(bid) in ENEMY_TURRET_TYPES and c.get_team(bid) != c.get_team()

    def _counter_sentinel_done(self, c: Controller):
        if self._counter_target_pos is None:
            return True
        if not c.is_in_vision(self._counter_target_pos):
            return False
        bid = c.get_tile_building_id(self._counter_target_pos)
        if bid is None:
            return False
        return c.get_entity_type(bid) == EntityType.SENTINEL and c.get_team(bid) == c.get_team()

    def _get_enemy_turrets(self, c: Controller, builds: list[EntityType]):
        result = []
        for bid in builds:
            if c.get_team(bid) == c.get_team():
                continue
            if c.get_entity_type(bid) in ENEMY_TURRET_TYPES:
                result.append(c.get_position(bid))
        return result

    # =========================================================================
    # P1 – Counter turret
    # =========================================================================

    def _update_counter_target(self, c: Controller, builds: list[EntityType]):
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

    def _run_counter_turret(self, c: Controller, builds: list[EntityType]):
        current = c.get_position()
        if self._counter_target_pos is not None:
            if (not self._enemy_turret_still_alive(c, self._counter_enemy_turret)
                    or self._counter_sentinel_done(c)):
                self._counter_target_pos = None
                self._counter_dir = None
                self._counter_enemy_turret = None
            else:
                c.draw_indicator_dot(self._counter_target_pos, 255, 0, 0)
                # Construir barrera si no hay dinero para sentinel, o sentinel si ya hay dinero
                titanium = c.get_global_resources()[0]
                precio_sentinel = c.get_sentinel_cost()[0]
                precio_barrier = c.get_barrier_cost()[0]
                done = False
                
                if titanium >= precio_sentinel:
                    done = self.construir(c, self._counter_target_pos,
                                        EntityType.SENTINEL, self._counter_dir)
                elif titanium >= precio_barrier:
                    self.construir(c, self._counter_target_pos,
                                        EntityType.BARRIER)
                    
                if done:
                    self._counter_target_pos = None
                    self._counter_dir = None
                    self._counter_enemy_turret = None
                return True

        self._update_counter_target(c, builds)
        if self._counter_target_pos is not None:
            c.draw_indicator_dot(self._counter_target_pos, 255, 0, 0)
            done = self.construir(c, self._counter_target_pos,
                                  EntityType.SENTINEL, self._counter_dir)
            if done:
                self._counter_target_pos = None
                self._counter_dir = None
                self._counter_enemy_turret = None
            return True
        return False

    # =========================================================================
    # P2 – Intercept enemy bot (splitter + sentinel)
    # =========================================================================

    def _get_nearby_enemy_bots(self, c: Controller):
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

    def _enemy_bot_still_present(self, c: Controller, enemy_pos: Position):
        if not c.is_in_vision(enemy_pos):
            return False
        uid = c.get_tile_builder_bot_id(enemy_pos)
        if uid is not None and c.get_team(uid) != c.get_team():
            return True
        for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
                  Direction.NORTHEAST, Direction.NORTHWEST,
                  Direction.SOUTHEAST, Direction.SOUTHWEST]:
            adj = enemy_pos.add(d)
            if not self._in_bounds(adj) or not c.is_in_vision(adj):
                continue
            uid2 = c.get_tile_builder_bot_id(adj)
            if uid2 is not None and c.get_team(uid2) != c.get_team():
                return True
        return False

    def _get_splitter_dir_from_feeder(self, c: Controller, conv_pos: Position, conv_dir: Direction):
        """
        Devuelve (splitter_dir, feeder_type) donde feeder_type es
        'harvester', 'conveyor', 'bridge', 'splitter' o None.

        Lógica:
          - Harvester adyacente aliado (cardinal):
              splitter_dir = harvester_pos.direction_to(conv_pos)
          - Conveyor/armoured_conveyor aliado apuntando a conv_pos:
              splitter_dir = dirección de ese feeder
          - Bridge/splitter aliado apuntando a conv_pos:
              splitter_dir = conv_dir (mantener original)
          - Sin feeder visible:
              splitter_dir = conv_dir
        """
        # 1. Harvester adyacente (cardinal) tiene prioridad
        for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
            adj = conv_pos.add(d)
            if not self._in_bounds(adj) or not c.is_in_vision(adj):
                continue
            bid = c.get_tile_building_id(adj)
            if bid is None:
                continue

            if (c.get_entity_type(bid) == EntityType.HARVESTER and c.get_tile_env(adj) == Environment.ORE_TITANIUM):
                return adj.direction_to(conv_pos), 'harvester'
            
        # 2. Edificios de transporte aliados cuyo output apunta a conv_pos
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES:
                continue
            pos = c.get_position(bid)
            if pos == conv_pos:
                continue
            if pos in self.layout_positions:
                continue
            if etype == EntityType.BRIDGE:
                try:
                    target = c.get_bridge_target(bid)
                except Exception:
                    continue
                if target == conv_pos:
                    return conv_dir, 'bridge'
            elif etype == EntityType.SPLITTER:
                try:
                    d = c.get_direction(bid)
                except Exception:
                    continue
                if (pos.add(d) == conv_pos):
                    pass
                elif pos.add(d.rotate_left().rotate_left()) == conv_pos:
                    d = d.rotate_left().rotate_left()
                elif pos.add(d.rotate_right().rotate_right()) == conv_pos:
                    d = d.rotate_right().rotate_right()
                else:
                    continue
                
                return d, 'splitter'
            else:  # CONVEYOR, ARMOURED_CONVEYOR
                try:
                    d = c.get_direction(bid)
                except Exception:
                    continue
                if pos.add(d) == conv_pos:
                    return d, 'conveyor'

        return conv_dir, None

    def _find_sentinel_spot(self, c: Controller, splitter_pos: Position, splitter_dir: Direction, enemy_pos: Position):
        """
        Busca casilla válida para el sentinel entre: izquierda, derecha y
        delante del splitter.

        Válida si:
          - En bounds y en visión
          - No en layout defensivo
          - No pared ni ore
          - No transporte aliado (no romper cadena)
          - Vacía, o road (propia → destroy, enemiga → fire), o sentinel aliado

        Devuelve (pos, dir_to_enemy, road_type) donde road_type es
        'allied', 'enemy' o None. Si ninguna es válida devuelve (None, None, None).
        """
        left_dir  = splitter_dir.rotate_left().rotate_left()
        right_dir = splitter_dir.rotate_right().rotate_right()
        front_dir = splitter_dir

        for side_dir in (left_dir, right_dir, front_dir):
            candidate = splitter_pos.add(side_dir)
            if not self._in_bounds(candidate) or not c.is_in_vision(candidate):
                continue
            if candidate in self.layout_positions:
                continue
            env = c.get_tile_env(candidate)
            if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                continue

            # Girar 45º si sentinel apuntase a su fuente de recursos
            dir_to_enemy = candidate.direction_to(enemy_pos)
            not_valid = candidate.direction_to(splitter_pos)
            if dir_to_enemy == not_valid:
                dir_to_enemy = dir_to_enemy.rotate_left()
            
            bid = c.get_tile_building_id(candidate)

            if bid is None:
                return candidate, dir_to_enemy, None

            etype = c.get_entity_type(bid)
            team  = c.get_team(bid)

            # Sentinel aliado existente: reutilizar
            if etype == EntityType.SENTINEL and team == c.get_team():
                return candidate, dir_to_enemy, None

            # Transporte aliado: no tocar
            if team == c.get_team() and etype in (
                EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE
            ):
                continue

            # Road: aceptar, hay que destruirla primero
            if etype == EntityType.ROAD:
                road_type = 'allied' if team == c.get_team() else 'enemy'
                return candidate, dir_to_enemy, road_type

            # Otro edificio: no válido
            continue

        return None, None, None

    def _find_best_conveyor_for_intercept(self, c: Controller, enemy_pos: Position):
        """
        Busca el mejor conveyor/armoured_conveyor aliado para la estructura
        splitter + sentinel. Itera candidatos (con recurso primero, luego vacíos,
        ambos ordenados por distancia al bot) y descarta aquellos para los que
        no existe ninguna casilla válida de sentinel.

        Devuelve (conv_pos, splitter_dir, sentinel_pos, sentinel_dir, road_type)
        o None si no hay candidato válido.
        """
        candidates_with = []
        candidates_empty = []

        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                continue
            pos = c.get_position(bid)
            if pos in self.layout_positions:
                continue
            try:
                conv_dir = c.get_direction(bid)
            except Exception:
                continue
            dist = pos.distance_squared(enemy_pos)
            splitter_dir, _ = self._get_splitter_dir_from_feeder(c, pos, conv_dir)
            entry = (dist, pos, splitter_dir)
            if c.get_stored_resource(bid) is not None:
                candidates_with.append(entry)
            else:
                candidates_empty.append(entry)

        candidates_with.sort()
        candidates_empty.sort()

        for _, conv_pos, splitter_dir in candidates_with + candidates_empty:
            s_pos, s_dir, road_type = self._find_sentinel_spot(
                c, conv_pos, splitter_dir, enemy_pos
            )
            if s_pos is None:
                continue  # No hay spot válido: descartar este conveyor
            return conv_pos, splitter_dir, s_pos, s_dir, road_type

        return None

    def _intercept_clear(self):
        self._intercept_enemy_pos = None
        self._intercept_splitter_pos = None
        self._intercept_splitter_dir = None
        self._intercept_sentinel_pos = None
        self._intercept_sentinel_dir = None
        self._intercept_sentinel_road = None

    def _intercept_setup(self, c: Controller, enemy_pos: Position):
        result = self._find_best_conveyor_for_intercept(c, enemy_pos)
        if result is None:
            return False
        conv_pos, splitter_dir, s_pos, s_dir, road_type = result
        self._intercept_enemy_pos = enemy_pos
        self._intercept_splitter_pos = conv_pos
        self._intercept_splitter_dir = splitter_dir
        self._intercept_sentinel_pos = s_pos
        self._intercept_sentinel_dir = s_dir
        self._intercept_sentinel_road = road_type
        return True

    def _run_intercept(self, c: Controller):
        """
        P2: interceptar bot enemigo con splitter + sentinel.
        Persistente hasta que el bot desaparezca o la instalación esté completa.
        """
        # Verificar objetivo activo
        if self._intercept_enemy_pos is not None:
            if not self._enemy_bot_still_present(c, self._intercept_enemy_pos):
                self._intercept_clear()
            else:
                # Actualizar dirección del sentinel con posición actual del bot
                nearby_bots = self._get_nearby_enemy_bots(c)
                if nearby_bots:
                    _, cur_enemy = nearby_bots[0]
                    self._intercept_enemy_pos = cur_enemy
                    if self._intercept_sentinel_pos is not None:
                        self._intercept_sentinel_dir = \
                            self._intercept_sentinel_pos.direction_to(cur_enemy)

        # Sin objetivo: buscar uno nuevo
        if self._intercept_enemy_pos is None:
            nearby_bots = self._get_nearby_enemy_bots(c)
            if not nearby_bots:
                return False
            _, enemy_pos = nearby_bots[0]
            if not self._intercept_setup(c, enemy_pos):
                return False

        current = c.get_position()

        # ── Paso 1: splitter ─────────────────────────────────────────────────
        if self._intercept_splitter_pos is not None:
            spl_pos = self._intercept_splitter_pos
            c.draw_indicator_dot(spl_pos, 255, 140, 0)

            # Guard: no consultar la casilla si está fuera de visión
            if not c.is_in_vision(spl_pos):
                d = self.navegador.moveTo(c, spl_pos, four_dirs=False)
                nxt = current.add(d)
                if c.can_build_road(nxt):
                    c.build_road(nxt)
                self._try_move(c, d)
                return True

            bid = c.get_tile_building_id(spl_pos)
            splitter_done = (bid is not None
                             and c.get_entity_type(bid) == EntityType.SPLITTER
                             and c.get_team(bid) == c.get_team())

            if not splitter_done:
                if bid is not None and c.get_team(bid) == c.get_team():
                    # Conveyor aliado: destruir primero
                    if current.distance_squared(spl_pos) > 2:
                        d = self.navegador.moveTo(c, spl_pos, four_dirs=False)
                        nxt = current.add(d)
                        if c.can_build_road(nxt):
                            c.build_road(nxt)
                        self._try_move(c, d)
                        return True
                    # Solo destruir si tenemos recursos para poner el splitter en el mismo turno
                    titanium = c.get_global_resources()[0]
                    precio = c.get_splitter_cost()[0]
                    if titanium >= precio and c.can_destroy(spl_pos):
                        c.destroy(spl_pos)
                # Casilla vacía: construir splitter
                self._construir_splitter(c, spl_pos, self._intercept_splitter_dir)
                return True

        # ── Paso 2: sentinel ─────────────────────────────────────────────────
        if self._intercept_sentinel_pos is None or self._intercept_sentinel_dir is None:
            return True

        sen_pos = self._intercept_sentinel_pos
        c.draw_indicator_dot(sen_pos, 255, 0, 0)

        # Guard: no consultar si está fuera de visión
        if not c.is_in_vision(sen_pos):
            d = self.navegador.moveTo(c, sen_pos, four_dirs=False)
            nxt = current.add(d)
            if c.can_build_road(nxt):
                c.build_road(nxt)
            self._try_move(c, d)
            return True

        bid = c.get_tile_building_id(sen_pos)
        sentinel_done = (bid is not None
                         and c.get_entity_type(bid) == EntityType.SENTINEL
                         and c.get_team(bid) == c.get_team())

        if sentinel_done:
            return True

        # Destruir road si hace falta antes de construir
        if self._intercept_sentinel_road is not None and bid is not None:
            etype = c.get_entity_type(bid)
            if etype == EntityType.ROAD:
                if self._intercept_sentinel_road == 'allied':
                    if current.distance_squared(sen_pos) > 2:
                        d = self.navegador.moveTo(c, sen_pos, four_dirs=False)
                        nxt = current.add(d)
                        if c.can_build_road(nxt):
                            c.build_road(nxt)
                        self._try_move(c, d)
                        return True
                    if c.can_destroy(sen_pos):
                        c.destroy(sen_pos)
                    return True
                else:  # enemy road
                    if current == sen_pos:
                        if c.can_fire(sen_pos):
                            c.fire(sen_pos)
                        if c.get_tile_building_id(sen_pos) is None:
                            self._intercept_sentinel_road = None
                            for d in [Direction.NORTH, Direction.EAST,
                                      Direction.SOUTH, Direction.WEST]:
                                if self._try_move(c, d):
                                    break
                    else:
                        if c.is_tile_passable(sen_pos):
                            d = self.navegador.moveTo(c, sen_pos, four_dirs=False)
                            nxt = current.add(d)
                            if c.can_build_road(nxt):
                                c.build_road(nxt)
                            self._try_move(c, d)
                    return True
            else:
                # Ya no hay road (fue destruida): limpiar flag
                self._intercept_sentinel_road = None

        # Construir sentinel
        self.construir(c, sen_pos, EntityType.SENTINEL, self._intercept_sentinel_dir)
        return True

    def _construir_splitter(self, c: Controller, objetivo: Position, direccion: Direction):
        current = c.get_position()
        if not c.is_in_vision(objetivo):
            return False
        bid = c.get_tile_building_id(objetivo)
        if bid is not None:
            if (c.get_entity_type(bid) == EntityType.SPLITTER
                    and c.get_team(bid) == c.get_team()):
                return True
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

    # =========================================================================
    # P3 – Broken chain detection
    # =========================================================================

    def _detect_broken_chain(self, c: Controller):
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
                if (c.get_team(dest_bid) == c.get_team()
                        and c.get_entity_type(dest_bid) in TRANSPORT_TYPES):
                    self._broken_chain_reported.discard(dest)
                    continue
                if c.get_team(dest_bid) == c.get_team():
                    continue
            if c.can_place_marker(dest):
                c.place_marker(dest, MARKER_BROKEN_CHAIN)
                self._broken_chain_reported.add(dest)
            c.draw_indicator_dot(dest, 255, 128, 0)
            return

    # =========================================================================
    # Patrulla
    # =========================================================================

    def _start_new_patrol(self, c: Controller):
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

    def _patrol_move(self, c: Controller):
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

    # =========================================================================
    # Construcción genérica
    # =========================================================================

    def construir(self, c: Controller, objetivo: Position, edificio: EntityType, direccion=Direction.CENTRE):
        current = c.get_position()
        if c.is_in_vision(objetivo):
            building_id = c.get_tile_building_id(objetivo)
        else:
            building_id = None
            
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
                
                # Solo destruir si tenemos dinero para construir el mismo turno
                titanium = c.get_global_resources()[0]
                precio = 0
                if edificio == EntityType.SENTINEL:
                    precio = c.get_sentinel_cost()[0]
                elif edificio == EntityType.BARRIER:
                    precio = c.get_barrier_cost()[0]
                if c.can_destroy(objetivo) and titanium >= precio:
                    c.destroy(objetivo)
                # return False
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
                    for d in [Direction.NORTH, Direction.EAST,
                              Direction.SOUTH, Direction.WEST,
                              Direction.NORTHEAST, Direction.SOUTHEAST,
                              Direction.SOUTHWEST, Direction.NORTHWEST]:
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

    # =========================================================================
    # run
    # =========================================================================

    def run(self, c: Controller):
        current = c.get_position()
        if c.get_hp() < c.get_max_hp() and c.can_heal(current):
            c.heal(current)
            c.draw_indicator_dot(current, 255, 50, 50)

        builds = c.get_nearby_buildings()

        # P1: torreta enemiga → sentinel sobre su fuente
        if self._run_counter_turret(c, builds):
            return

        # P2: bot enemigo en visión → splitter + sentinel
        if self._run_intercept(c):
            return

        # P4: curar edificios aliados dañados
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
            # P5: patrullar
            c.draw_indicator_dot(current, 0, 200, 255)
            self._patrol_move(c)