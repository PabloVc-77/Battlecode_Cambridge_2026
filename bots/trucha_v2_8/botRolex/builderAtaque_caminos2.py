"""
builderAtaque_caminos.py
========================
Bot de ataque que construye una cadena de recursos hasta el core enemigo.

FLUJO:
  Fase 0 – Localizar el core enemigo (por simetría).
  Fase 1 – Explorar hasta tener localizado 1 ore de titanio Y 1 de axionita.
           "Localizado" significa: tile visible con ore libre y al menos 1
           casilla cardinal adyacente libre, o harvester aliado existente con
           al menos 1 casilla cardinal adyacente libre.
           Al encontrar ambos, elige la casilla destino para el foundry: la
           casilla cardinal libre junto al harvester de titanio más cercana
           al core enemigo.
  Fase 2 – Construir harvester en los ores que aún no lo tengan.
  Fase 3 – Tender cadena de bridges desde el harvester de Ti hasta
           foundry_spot. Construir el foundry en foundry_spot.
  Fase 4 – Tender cadena de bridges (solo bridges, sin conveyors) desde
           foundry_spot hacia la casilla más próxima al core enemigo
           con dist² < 24. Cuando el anchor llega a dist² < 24, fin.

No se defiende nada en ninguna fase.
"""

from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav


# ── Constantes ────────────────────────────────────────────────────────────────

_CARD_DIRS = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)

# Distancia² al core enemigo en la que termina el camino de ataque
_ATTACK_RANGE_SQ = 24


# ── Helpers globales ──────────────────────────────────────────────────────────

def _in_bounds(pos: Position, w: int, h: int) -> bool:
    return 0 <= pos.x < w and 0 <= pos.y < h


def _free_cardinal_adj(c: Controller, pos: Position, w: int, h: int) -> list:
    """
    Casillas cardinales adyacentes a `pos` que están libres:
    sin edificio, o con edificio pasable, y no son WALL ni ore.
    Las casillas fuera de visión se incluyen provisionalmente.
    """
    result = []
    for d in _CARD_DIRS:
        adj = pos.add(d)
        if not _in_bounds(adj, w, h):
            continue
        if not c.is_in_vision(adj):
            result.append(adj)
            continue
        env = c.get_tile_env(adj)
        if env == Environment.WALL:
            continue
        bid = c.get_tile_building_id(adj)
        if bid is None or c.is_tile_passable(adj):
            result.append(adj)
    return result


# ─────────────────────────────────────────────────────────────────────────────

class BuilderAtaqueCaminos:

    def __init__(self, c: Controller):
        self.nav   = bugnav.BugNav()
        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()

        # ── Core aliado ───────────────────────────────────────────────────────
        self.spawn: Position | None = None

        # ── Core enemigo ──────────────────────────────────────────────────────
        self.enemy_core_pos:        Position | None = None
        self.enemy_core_candidates: list            = []
        self.simetry:               int             = 0

        # ── Objetivos de ore ──────────────────────────────────────────────────
        self.ti_ore:  Position | None = None   # ore / harvester de titanio
        self.ax_ore:  Position | None = None   # ore / harvester de axionita

        # Casilla cardinal junto al Ti donde irá el foundry
        self.foundry_spot: Position | None = None

        # ── Anchor del camino de bridges en construcción ───────────────────────
        # En fase 3: último bridge colocado (o foundry_spot como valor inicial).
        # En fase 4: último bridge colocado (o foundry_spot como valor inicial).
        self.bridge_anchor: Position | None = None

        # ── Modo ──────────────────────────────────────────────────────────────
        self.mode: int = 0
        #   0 – buscar core enemigo
        #   1 – explorar hasta tener ti_ore Y ax_ore
        #   2 – construir harvesters que falten
        #   3 – tender puentes hasta foundry_spot y construir foundry
        #   4 – tender puentes hasta casilla cerca del core enemigo

        # Detectar core aliado al inicio
        for b in c.get_nearby_buildings():
            if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) == c.get_team():
                self.spawn = c.get_position(b)
                break

        if self.spawn is not None:
            self._init_enemy_candidates()

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _ib(self, pos: Position) -> bool:
        return _in_bounds(pos, self.map_w, self.map_h)

    def _try_move(self, c: Controller, d: Direction) -> bool:
        if d == Direction.CENTRE:
            return False
        dest = c.get_position().add(d)
        if not self._ib(dest):
            return False
        if c.can_move(d):
            c.move(d)
            return True
        return False

    def _navigate_to(self, c: Controller, dest: Position):
        current  = c.get_position()
        d        = self.nav.moveTo(c, dest, four_dirs=False)
        next_pos = current.add(d)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        self._try_move(c, d)

    def _init_enemy_candidates(self):
        x, y = self.spawn.x, self.spawn.y
        w, h = self.map_w, self.map_h
        self.enemy_core_candidates = [
            Position(w - 1 - x, y),
            Position(x, h - 1 - y),
            Position(w - 1 - x, h - 1 - y),
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # ENTRADA PRINCIPAL
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, c: Controller):
        current = c.get_position()
        if c.can_heal(current):
            c.heal(current)

        # Inicialización tardía
        if self.spawn is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) == c.get_team():
                    self.spawn = c.get_position(b)
                    self._init_enemy_candidates()
                    break

        if self.mode == 0:
            c.draw_indicator_dot(current, 255, 255, 0)
            self._fase0(c)
        elif self.mode == 1:
            c.draw_indicator_dot(current, 0, 200, 255)
            self._fase1(c)
        elif self.mode == 2:
            c.draw_indicator_dot(current, 24, 184, 69)
            self._fase2(c)
        elif self.mode == 3:
            c.draw_indicator_dot(current, 204, 16, 73)
            self._fase3(c)
        elif self.mode == 4:
            c.draw_indicator_dot(current, 255, 100, 0)
            self._fase4(c)

    # ──────────────────────────────────────────────────────────────────────────
    # FASE 0: Localizar core enemigo
    # ──────────────────────────────────────────────────────────────────────────

    def _fase0(self, c: Controller):
        # ¿Ya lo vemos?
        for b in c.get_nearby_buildings():
            if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team():
                self.enemy_core_pos = c.get_position(b)
                self.mode = 1
                return

        if not self.enemy_core_candidates:
            return

        target  = self.enemy_core_candidates[self.simetry % len(self.enemy_core_candidates)]
        current = c.get_position()
        c.draw_indicator_line(current, target, 255, 140, 0)
        self._navigate_to(c, target)

        if c.is_in_vision(target):
            bid = c.get_tile_building_id(target)
            if (bid is not None
                    and c.get_entity_type(bid) == EntityType.CORE
                    and c.get_team(bid) != c.get_team()):
                self.enemy_core_pos = target
                self.mode = 1
            else:
                self.simetry += 1

    # ──────────────────────────────────────────────────────────────────────────
    # FASE 1: Explorar hasta localizar ti_ore y ax_ore
    # ──────────────────────────────────────────────────────────────────────────

    def _ore_valid(self, c: Controller, tile: Position, ore_env: Environment) -> bool:
        """
        True si el tile es un ore del tipo indicado que podemos usar:
        - Tile con ore libre (sin edificio) y al menos 1 adyacente cardinal libre, o
        - Tile con harvester aliado y al menos 1 adyacente cardinal libre.
        """
        if not self._ib(tile) or not c.is_in_vision(tile):
            return False
        if c.get_tile_env(tile) != ore_env:
            return False
        bid = c.get_tile_building_id(tile)
        if bid is not None:
            et = c.get_entity_type(bid)
            if et == EntityType.HARVESTER and c.get_team(bid) == c.get_team():
                return bool(_free_cardinal_adj(c, tile, self.map_w, self.map_h))
            return False   # otro edificio bloquea el ore
        return bool(_free_cardinal_adj(c, tile, self.map_w, self.map_h))

    def _scan_ores(self, c: Controller):
        for tile in c.get_nearby_tiles():
            if not c.is_in_vision(tile):
                continue
            env = c.get_tile_env(tile)
            if self.ti_ore is None and env == Environment.ORE_TITANIUM:
                if self._ore_valid(c, tile, Environment.ORE_TITANIUM):
                    self.ti_ore = tile
            if self.ax_ore is None and env == Environment.ORE_AXIONITE:
                if self._ore_valid(c, tile, Environment.ORE_AXIONITE):
                    self.ax_ore = tile

    def _choose_foundry_spot(self, c: Controller) -> "Position | None":
        """
        Elige la casilla cardinal libre junto al harvester de axionita
        más cercana al core enemigo.
        """
        candidates = _free_cardinal_adj(c, self.ax_ore, self.map_w, self.map_h)
        valid = []
        for p in candidates:
            if not c.is_in_vision(p):
                valid.append(p)
                continue
            env = c.get_tile_env(p)
            if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                continue
            valid.append(p)
        if not valid or self.enemy_core_pos is None:
            return None
        return min(valid, key=lambda p: p.distance_squared(self.enemy_core_pos))

    def _fase1(self, c: Controller):
        self._scan_ores(c)

        if self.ti_ore is not None and self.ax_ore is not None:
            spot = self._choose_foundry_spot(c)
            if spot is not None:
                self.foundry_spot  = spot
                self.bridge_anchor = spot   # valor inicial para fase 3
                self.mode = 2
                self._fase2(c)
                return
            # foundry_spot aún no determinable: movernos cerca del Ti
            self._navigate_to(c, self.ti_ore)
            return

        # Explorar hasta encontrar ambos
        current  = c.get_position()
        move_dir = self.nav.moveExplore(c, four_dirs=False)
        next_pos = current.add(move_dir)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        self._try_move(c, move_dir)

    # ──────────────────────────────────────────────────────────────────────────
    # FASE 2: Construir harvesters
    # ──────────────────────────────────────────────────────────────────────────

    def _has_allied_harvester(self, c: Controller, tile: Position) -> bool:
        if not c.is_in_vision(tile):
            return False
        bid = c.get_tile_building_id(tile)
        return (bid is not None
                and c.get_entity_type(bid) == EntityType.HARVESTER
                and c.get_team(bid) == c.get_team())

    def _build_harvester_at(self, c: Controller, tile: Position) -> bool:
        """
        Construye harvester en `tile`. Devuelve True si ya existe o recién colocado.
        """
        if self._has_allied_harvester(c, tile):
            return True

        current = c.get_position()

        if current == tile:
            for d in _CARD_DIRS:
                if self._try_move(c, d):
                    return False
            return False

        if current.distance_squared(tile) > 2:
            self._navigate_to(c, tile)
            return False

        if c.can_build_harvester(tile):
            c.build_harvester(tile)
            return True

        return False

    def _fase2(self, c: Controller):
        # Primero axionita, luego titanio
        if not self._has_allied_harvester(c, self.ax_ore):
            if not self._build_harvester_at(c, self.ax_ore):
                return
            
        if not self._has_allied_harvester(c, self.ti_ore):
            if not self._build_harvester_at(c, self.ti_ore):
                return
        

        # Ambos listos → fase 3
        self.mode = 3
        self._fase3(c)

    # ──────────────────────────────────────────────────────────────────────────
    # FASE 3: Tender bridges desde el Ti hasta foundry_spot y poner foundry
    # ──────────────────────────────────────────────────────────────────────────

    def _fase3(self, c: Controller):
        # ¿Ya hay foundry en foundry_spot?
        if c.is_in_vision(self.foundry_spot):
            bid = c.get_tile_building_id(self.foundry_spot)
            if (bid is not None
                    and c.get_entity_type(bid) == EntityType.FOUNDRY
                    and c.get_team(bid) == c.get_team()):
                self.bridge_anchor = self.foundry_spot
                self.mode = 4
                self._fase4(c)
                return

        # ¿La cadena ya llega a foundry_spot?
        if self._chain_feeds(c, self.foundry_spot):
            if self._build_foundry(c, self.foundry_spot):
                self.bridge_anchor = self.foundry_spot
                self.mode = 4
                self._fase4(c)
            return

        # Continuar tendiendo bridges
        anchor = self.bridge_anchor   # último bridge puesto (o foundry_spot inicialmente)

        if anchor == self.foundry_spot:
            # Primer bridge: origen = casilla cardinal del Ti más cercana a foundry_spot
            origin = self._best_adj(c, self.ti_ore, exclude=self.foundry_spot)
            if origin is None:
                self._navigate_to(c, self.ti_ore)
                return
            self._place_next_bridge(c, origin, self.foundry_spot)
        else:
            # Continuar desde el output del bridge en anchor
            next_origin = self._bridge_output(c, anchor)
            self._place_next_bridge(c, next_origin, self.foundry_spot)

    def _chain_feeds(self, c: Controller, dest: Position) -> bool:
        """
        True si algún bridge/conveyor aliado visible tiene como output `dest`.
        """
        if not c.is_in_vision(dest):
            return False
        for b in c.get_nearby_buildings():
            if c.get_team(b) != c.get_team():
                continue
            et   = c.get_entity_type(b)
            bpos = c.get_position(b)
            try:
                if et == EntityType.BRIDGE and c.get_bridge_target(b) == dest:
                    return True
                if et in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                    if bpos.add(c.get_direction(b)) == dest:
                        return True
            except Exception:
                pass
        return False

    def _build_foundry(self, c: Controller, pos: Position) -> bool:
        """
        Construye foundry en `pos`. Devuelve True si ya existe o recién construido.
        """
        current = c.get_position()

        if c.is_in_vision(pos):
            bid = c.get_tile_building_id(pos)
            if bid is not None:
                et = c.get_entity_type(bid)
                if et == EntityType.FOUNDRY and c.get_team(bid) == c.get_team():
                    return True
                # Limpiar si es aliado y destruible
                if c.get_team(bid) == c.get_team() and c.can_destroy(pos):
                    c.destroy(pos)
                    return False

        if current.distance_squared(pos) > 2:
            self._navigate_to(c, pos)
            return False

        if current == pos:
            for d in _CARD_DIRS:
                if self._try_move(c, d):
                    return False
            return False

        if c.can_build_foundry(pos):
            c.build_foundry(pos)
            return True

        return False

    def _best_adj(self, c: Controller, ref: Position, exclude: Position) -> "Position | None":
        """
        Casilla cardinal adyacente a `ref` (distinta de `exclude`) libre,
        la más cercana al foundry_spot.
        """
        best = None
        best_d = 10**9
        for d in _CARD_DIRS:
            adj = ref.add(d)
            if not self._ib(adj) or adj == exclude:
                continue
            if c.is_in_vision(adj):
                env = c.get_tile_env(adj)
                if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                    continue
                bid = c.get_tile_building_id(adj)
                if bid is not None and not c.is_tile_passable(adj):
                    continue
            dist = adj.distance_squared(self.foundry_spot)
            if dist < best_d:
                best_d = dist
                best   = adj
        return best

    def _bridge_output(self, c: Controller, anchor: Position) -> Position:
        """
        Devuelve el output del bridge en `anchor`, o `anchor` si no hay bridge.
        """
        if c.is_in_vision(anchor):
            bid = c.get_tile_building_id(anchor)
            if bid is not None and c.get_entity_type(bid) == EntityType.BRIDGE and c.get_team(bid) == c.get_team():
                try:
                    return c.get_bridge_target(bid)
                except Exception:
                    pass
        return anchor

    def _place_next_bridge(self, c: Controller, origin: Position, dest: Position):
        """
        Coloca el siguiente bridge: en `origin` apuntando hacia `dest`
        (o hacia un punto intermedio si dist² > 9).
        Actualiza self.bridge_anchor si lo coloca.
        """
        current = c.get_position()

        # Destino efectivo (dentro de radio 3 desde origin)
        eff_dest = self._intermediate(origin, dest)

        # Acercarse a origin
        if current.distance_squared(origin) > 2:
            self._navigate_to(c, origin)
            return

        # No podemos estar encima del origen para construir
        if current == origin:
            for d in _CARD_DIRS:
                adj = origin.add(d)
                if self._ib(adj) and adj != dest and self._try_move(c, d):
                    return
            return

        # Revisar si ya hay un bridge aliado en origin
        if c.is_in_vision(origin):
            bid = c.get_tile_building_id(origin)
            if bid is not None:
                et = c.get_entity_type(bid)
                if et == EntityType.BRIDGE and c.get_team(bid) == c.get_team():
                    # Ya existe: avanzar el anchor
                    self.bridge_anchor = origin
                    return
                # Limpiar si es aliado
                if c.get_team(bid) == c.get_team() and c.can_destroy(origin):
                    c.destroy(origin)
                    return

        if c.can_build_bridge(origin, eff_dest):
            c.build_bridge(origin, eff_dest)
            self.bridge_anchor = origin

    def _intermediate(self, origin: Position, dest: Position) -> Position:
        """
        Si origin→dest está a dist² > 9, devuelve la casilla dentro del
        radio 3 de origin más cercana a dest.
        """
        if origin.distance_squared(dest) <= 9:
            return dest
        best   = None
        best_d = 10**9
        for ddx in range(-3, 4):
            for ddy in range(-3, 4):
                if ddx * ddx + ddy * ddy > 9 or (ddx == 0 and ddy == 0):
                    continue
                cand = Position(origin.x + ddx, origin.y + ddy)
                if not self._ib(cand):
                    continue
                d = cand.distance_squared(dest)
                if d < best_d:
                    best_d = d
                    best   = cand
        return best if best is not None else dest

    # ──────────────────────────────────────────────────────────────────────────
    # FASE 4: Tender bridges desde el foundry hasta cerca del core enemigo
    # ──────────────────────────────────────────────────────────────────────────

    def _fase4(self, c: Controller):
        if self.enemy_core_pos is None:
            return

        anchor = self.bridge_anchor
        if anchor is None:
            anchor = self.foundry_spot

        # Comprobar si el output del bridge en anchor ya está en rango
        next_origin = self._bridge_output(c, anchor)

        c.draw_indicator_line(c.get_position(), self.enemy_core_pos, 255, 100, 0)

        if next_origin.distance_squared(self.enemy_core_pos) < _ATTACK_RANGE_SQ:
            # Misión completada
            c.draw_indicator_dot(c.get_position(), 255, 255, 255)
            self.bridge_anchor = next_origin
            return

        self._place_next_bridge(c, next_origin, self.enemy_core_pos)