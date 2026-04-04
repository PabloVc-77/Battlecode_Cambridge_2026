from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav

# ---------------------------------------------------------------------------
# Prioridad de curación: menor número = mayor prioridad
# ---------------------------------------------------------------------------
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
    EntityType.CORE,
    EntityType.FOUNDRY,
    EntityType.HARVESTER,
    EntityType.LAUNCHER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.CONVEYOR,
    EntityType.BARRIER,
})

TRANSPORT_TYPES: frozenset[EntityType] = frozenset({
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
})


def _entity_priority(entity_type: EntityType) -> int:
    return HEAL_PRIORITY.get(entity_type, 99)


def _output_of(c: Controller, bid: int) -> Position | None:
    """
    Devuelve la posición de salida del edificio de transporte con id `bid`.
    - Bridge  → get_bridge_target()
    - Conveyor / AConveyor / Splitter → pos + dirección
    - Harvester / otros → None
    """
    etype = c.get_entity_type(bid)
    pos = c.get_position(bid)
    if etype == EntityType.BRIDGE:
        try:
            return c.get_bridge_target(bid)
        except Exception:
            return None
    if etype in (EntityType.CONVEYOR,
                 EntityType.ARMOURED_CONVEYOR,
                 EntityType.SPLITTER):
        try:
            return pos.add(c.get_direction(bid))
        except Exception:
            return None
    return None


class Healer:
    def __init__(self, c: Controller):
        self.navegador = bugnav.BugNav()

        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()

        # Diccionario pos -> id de todos los edificios aliados de transporte conocidos
        # Guardamos el id para poder llamar get_direction / get_bridge_target sin buscar
        self.known_transport: dict[Position, int] = {}

        # ── Patrulla ────────────────────────────────────────────────────────
        # Lista de waypoints [core_pos, end_bridge, ..., harvester].
        # Se construye dinámicamente: empezamos con [core_pos, end_bridge] y
        # añadimos un waypoint nuevo cada vez que estamos en visión del último.
        self.patrol_route: list[Position] = []

        # Índice del waypoint al que nos dirigimos ahora.
        self.patrol_index: int = 0

        # Dirección de recorrido: +1 = hacia el harvester, -1 = de vuelta a la base.
        self.patrol_direction: int = 1

        # ¿Hemos llegado al final de la cadena (harvester o eslabón sin sucesor)?
        self.reached_end: bool = False

        # Qué end_bridge usamos en el ciclo actual (rotamos entre ciclos).
        self._eb_index: int = 0

        # Posición del core.
        self.core_pos: Position | None = None

        # end_bridges: casillas de entrada a la base.
        self.end_bridges: list[Position] = []

        # Inicializar core y end_bridges
        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_entity_type(b) == EntityType.CORE:
                self.core_pos = c.get_position(b)
                break

        if self.core_pos is not None:
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

    # -----------------------------------------------------------------------
    # Bounds
    # -----------------------------------------------------------------------

    def _in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    # -----------------------------------------------------------------------
    # Movimiento
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Actualización del mapa de transporte conocido
    # -----------------------------------------------------------------------

    def _update_known_transport(self, c: Controller):
        """
        Mantiene known_transport: pos → bid de edificios de transporte aliados en visión.
        También registra harvesters para detectar el final de la cadena.
        """
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES and etype != EntityType.HARVESTER:
                continue
            pos = c.get_position(bid)
            self.known_transport[pos] = bid

        # Limpiar posiciones que ya no tienen el edificio aliado
        to_remove = []
        for pos, bid in self.known_transport.items():
            if not c.is_in_vision(pos):
                continue
            actual = c.get_tile_building_id(pos)
            if actual is None or c.get_team(actual) != c.get_team():
                to_remove.append(pos)
        for pos in to_remove:
            del self.known_transport[pos]

    # -----------------------------------------------------------------------
    # Detección de edificios dañados
    # -----------------------------------------------------------------------

    def _get_damaged_targets(self, c: Controller) -> list[tuple[int, int, Position]]:
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
                prio = _entity_priority(etype)
                dist = current.distance_squared(pos)
                damaged.append((prio, dist, pos))
        damaged.sort(key=lambda x: (x[0], x[1]))
        return damaged

    # -----------------------------------------------------------------------
    # Búsqueda del siguiente eslabón hacia el harvester
    # -----------------------------------------------------------------------

    def _find_feeder_of(self, c: Controller, target_pos: Position) -> Position | None:
        """
        Busca en known_transport un edificio aliado de transporte cuyo OUTPUT
        sea `target_pos`. Ese edificio es el "anterior" en la cadena (más cerca
        del harvester). Si hay varios, elige el que está en visión.

        NOTA: Este es el punto clave que el código original tenía mal.
        El original buscaba quién alimenta a target_pos para ir "al revés"
        del flujo, que es justamente lo que queremos: ir del core al harvester
        siguiendo la cadena de transporte en sentido inverso al flujo de recursos.

        Lo que fallaba era:
          1. Se llamaba desde `_follow_chain_from` con start=end_bridge, pero luego
             en `_build_patrol_route` se insertaba el core ANTES del end_bridge,
             de modo que la cadena empezaba yendo del end_bridge hacia el core
             (en la dirección equivocada) en lugar de alejarse de él.
          2. Se construía toda la ruta de golpe al inicio cuando known_buildings
             estaba casi vacío, así que la cadena salía con 0-1 eslabones.
          3. Se llamaba en cada tick de _patrol_move con el ÚLTIMO elemento,
             generando duplicados y sobreescribiendo la ruta.
        """
        for pos, bid in self.known_transport.items():
            if pos == target_pos:
                continue
            if not c.is_in_vision(pos):
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES:
                continue
            out = _output_of(c, bid)
            if out == target_pos:
                return pos
        return None

    # -----------------------------------------------------------------------
    # Lógica de patrulla
    # -----------------------------------------------------------------------

    def _start_new_patrol(self, c: Controller):
        """
        Inicia un nuevo ciclo de patrulla.
        Busca el end_bridge activo (con conveyor/bridge aliado) rotando _eb_index,
        y construye la ruta inicial: [core_pos, end_bridge].
        """
        if not self.end_bridges or self.core_pos is None:
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
            # Encontrado: arrancar desde aquí
            self._eb_index = (idx + 1) % n  # rotar para el siguiente ciclo
            self.patrol_route = [self.core_pos, eb]
            self.patrol_index = 0
            self.patrol_direction = 1
            self.reached_end = False
            return

        # Ningún end_bridge activo visible: quedarse en el core
        self.patrol_route = [self.core_pos]
        self.patrol_index = 0
        self.patrol_direction = 1
        self.reached_end = False

    def _try_extend_route(self, c: Controller):
        """
        Intenta añadir UN nuevo waypoint al final de patrol_route.
        Se llama justo después de llegar a un waypoint, cuando ya tenemos
        visión de los alrededores desde esa posición.

        Busca en known_transport (actualizado este tick) un edificio aliado
        de transporte cuyo OUTPUT apunte al último waypoint. Ese edificio es
        el eslabón anterior en el flujo de recursos, es decir, el siguiente
        paso hacia el harvester desde nuestra perspectiva.

        Si no encuentra ninguno, marca reached_end = True para que el healer
        invierta dirección en el siguiente tick.
        """
        if not self.patrol_route:
            return
        last = self.patrol_route[-1]
        feeder = self._find_feeder_of(c, last)

        if feeder is None or feeder in self.patrol_route:
            # No hay sucesor visible desde aquí: fin de cadena conocida
            self.reached_end = True
            return

        self.patrol_route.append(feeder)

        # Si el feeder es un harvester, el siguiente paso también es el fin
        bid = self.known_transport.get(feeder)
        if bid is not None and c.get_entity_type(bid) == EntityType.HARVESTER:
            self.reached_end = True

    def _patrol_move(self, c: Controller):
        current = c.get_position()

        # Si la ruta está vacía, iniciar un ciclo nuevo
        if not self.patrol_route:
            self._start_new_patrol(c)
            if not self.patrol_route:
                c.draw_indicator_dot(current, 128, 128, 128)
                return

        # Asegurar que el índice es válido
        self.patrol_index = max(0, min(self.patrol_index, len(self.patrol_route) - 1))
        target = self.patrol_route[self.patrol_index]

        # ── Comprobar que el waypoint actual sigue siendo válido ─────────────
        if c.is_in_vision(target) and target != self.core_pos:
            bid = c.get_tile_building_id(target)
            if bid is None or c.get_team(bid) != c.get_team():
                self._start_new_patrol(c)
                return

        # ── Comprobar si llegamos al waypoint actual ──────────────────────────
        if current == target:
            if self.patrol_direction == 1 and not self.reached_end:
                # Acabamos de llegar: ahora tenemos visión desde aquí,
                # intentar descubrir el siguiente eslabón de la cadena.
                self._try_extend_route(c)

            next_index = self.patrol_index + self.patrol_direction

            if next_index < 0:
                # Volvimos al core: iniciar nuevo ciclo rotando end_bridge
                self._start_new_patrol(c)
                return

            if next_index >= len(self.patrol_route):
                # Fin de ruta: invertir dirección
                self.patrol_direction = -1
                # No decrementamos aquí: el siguiente tick ya irá al anterior
                return

            self.patrol_index = next_index
            target = self.patrol_route[self.patrol_index]

        # ── Dibujar y moverse ────────────────────────────────────────────────
        c.draw_indicator_dot(target, 0, 200, 255)
        c.draw_indicator_line(current, target, 0, 200, 255)

        siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
        self._try_move(c, siguiente_dir)

    # -----------------------------------------------------------------------
    # Loop principal
    # -----------------------------------------------------------------------

    def run(self, c: Controller):
        current = c.get_position()

        # 1. Actualizar mapa de transporte conocido
        self._update_known_transport(c)

        # 2. AUTO-CURACIÓN: primera prioridad si tenemos daño
        my_hp = c.get_hp()
        my_max_hp = c.get_max_hp()
        if my_hp < my_max_hp and c.can_heal(current):
            c.heal(current)
            c.draw_indicator_dot(current, 255, 50, 50)
            return

        # 3. Buscar edificios aliados dañados en visión
        damaged = self._get_damaged_targets(c)

        if damaged:
            prio, dist_sq, target_pos = damaged[0]
            c.draw_indicator_dot(target_pos, 255, 80, 0)
            c.draw_indicator_line(current, target_pos, 255, 80, 0)

            if c.can_heal(target_pos):
                c.heal(target_pos)
                c.draw_indicator_dot(current, 0, 255, 80)
            else:
                # Curar otro objetivo en rango de paso si hay acción libre
                if c.get_action_cooldown() == 0:
                    for _, _, alt_pos in damaged[1:]:
                        if current.distance_squared(alt_pos) <= 2 and c.can_heal(alt_pos):
                            c.heal(alt_pos)
                            break

                siguiente_dir = self.navegador.moveTo(c, target_pos, four_dirs=False)
                self._try_move(c, siguiente_dir)
        else:
            # Sin daño — patrullar por la red de transporte
            c.draw_indicator_dot(current, 0, 200, 255)
            self._patrol_move(c)