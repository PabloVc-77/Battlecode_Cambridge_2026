"""
map_symmetry.py — Detector de simetría de mapa para Battlecode Cambridge

FUENTES DE INFORMACIÓN VÁLIDAS
───────────────────────────────
Solo se usan datos estáticos e inmutables del mapa:
  - Environment.WALL          → terreno bloqueado permanente
  - Environment.ORE_TITANIUM  → mineral fijo
  - Environment.ORE_AXIONITE  → mineral fijo
  - Core enemigo              → una sola observación confirma la simetría directamente

Las construcciones (conveyors, barriers…) NO se usan: son dinámicas y
hacen que un tile cambie de estado con el tiempo.

SIMETRÍAS POSIBLES
──────────────────
  - HORIZONTAL  : reflejo en eje Y  → sim(x, y) = (W-1-x, y)
  - VERTICAL    : reflejo en eje X  → sim(x, y) = (x, H-1-y)
  - ROTATIONAL  : rotación 180°     → sim(x, y) = (W-1-x, H-1-y)

LÓGICA DE DESCARTE
──────────────────
Para cada hipótesis viva, cuando se observa un tile con entorno E en (x,y),
se calcula la posición simétrica (x', y'). Si (x', y') ya está en el caché
con un entorno distinto → contradicción → hipótesis descartada.

Cuando solo queda una hipótesis → simetría CONFIRMADA.

Atajo rápido: si se localiza el core enemigo, la posición de su centro se
compara con la predicción de cada hipótesis; las que no coincidan se descartan
de golpe (normalmente confirma en un solo tick).

INTEGRACIÓN CON BUGNAV
──────────────────────
1. Instancia global en bugnav.py (o módulo de coordinación):

       from map_symmetry import MapSymmetry
       MAP_SYM = MapSymmetry()

2. En BugNav._update_map(), para cada tile visible añadir:

       env = c.get_tile_env(pos)
       MAP_SYM.update_terrain(pos, env, w, h)   # filtra EMPTY internamente

3. Cuando se detecte el core enemigo en la lógica del bot:

       # core_id viene de get_nearby_buildings() o get_nearby_entities()
       if (c.get_entity_type(core_id) == EntityType.CORE
               and c.get_team(core_id) != c.get_team()):
           enemy_center = c.get_position(core_id)
           MAP_SYM.update_enemy_core(my_core_pos, enemy_center, w, h)

4. Consultar desde cualquier módulo:

       from bugnav import MAP_SYM
       enemy_core = MAP_SYM.symmetric_pos(my_core_pos, w, h)
       if MAP_SYM.confirmed():
           print(f"Simetría: {MAP_SYM.get()}")
"""

from __future__ import annotations
from enum import Enum
from cambc import Position, Environment


# ---------------------------------------------------------------------------
# Enum público
# ---------------------------------------------------------------------------

class Symmetry(Enum):
    HORIZONTAL = "horizontal"   # sim(x,y) = (W-1-x, y)
    VERTICAL   = "vertical"     # sim(x,y) = (x, H-1-y)
    ROTATIONAL = "rotational"   # sim(x,y) = (W-1-x, H-1-y)


# ---------------------------------------------------------------------------
# Transformaciones simétricas
# ---------------------------------------------------------------------------

def _sym_pos(sym: Symmetry, pos: Position, w: int, h: int) -> Position:
    x, y = pos.x, pos.y
    if sym == Symmetry.HORIZONTAL:
        return Position(w - 1 - x, y)
    if sym == Symmetry.VERTICAL:
        return Position(x, h - 1 - y)
    return Position(w - 1 - x, h - 1 - y)  # ROTATIONAL


# ---------------------------------------------------------------------------
# Detector de simetría
# ---------------------------------------------------------------------------

class MapSymmetry:
    """
    Detector incremental de simetría de mapa basado únicamente en
    terreno estático (muros y mineral) y la posición del core enemigo.

    Uso mínimo:
        sym = MapSymmetry()

        # cada tick, para cada tile visible:
        sym.update_terrain(pos, c.get_tile_env(pos), w, h)

        # cuando se vea el core enemigo:
        sym.update_enemy_core(my_core_pos, c.get_position(enemy_core_id), w, h)

        # consultar:
        sym.confirmed()                        # bool
        sym.get()                              # Symmetry | None
        sym.symmetric_pos(pos, w, h)           # posición simétrica
    """

    def __init__(self) -> None:
        self._alive: set[Symmetry] = {
            Symmetry.HORIZONTAL,
            Symmetry.VERTICAL,
            Symmetry.ROTATIONAL,
        }
        # Caché de terreno estático observado: pos → Environment
        # Solo contiene tiles con env en _STATIC_ENVS
        self._terrain: dict[Position, Environment] = {}

        self._w: int = 0
        self._h: int = 0

        self._confirmed: Symmetry | None = None

    # ──────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────

    def update_terrain(self, pos: Position, env: Environment,
                       w: int, h: int) -> None:
        """
        Registra el entorno de un tile y descarta hipótesis inconsistentes.

        Internamente ignora los tiles con env == Environment.EMPTY, ya que
        no son inmutables (pueden tener edificios construidos encima).

        Args:
            pos: posición del tile.
            env: valor devuelto por c.get_tile_env(pos).
            w, h: dimensiones del mapa.
        """
        if self._w == 0:
            self._w, self._h = w, h

        # Si ya teníamos este tile con el mismo valor, nada nuevo
        if self._terrain.get(pos) == env:
            return

        self._terrain[pos] = env

        if self._confirmed is not None:
            return  # ya confirmada, seguimos cacheando pero no comprobamos

        self._check_contradictions(pos, env, w, h)

    def update_enemy_core(self, my_core: Position, enemy_core: Position,
                          w: int, h: int) -> None:
        """
        Confirma (o descarta) hipótesis usando la posición central del core enemigo.

        El core ocupa 9 casillas (3×3). enemy_core debe ser la posición central
        obtenida con c.get_position(core_id), donde core_id es el id del core
        enemigo visto.

        Este método normalmente confirma la simetría en un único tick.

        Args:
            my_core:    posición central del core propio.
            enemy_core: posición central del core enemigo observado.
            w, h:       dimensiones del mapa.
        """
        if self._confirmed is not None:
            return
        if self._w == 0:
            self._w, self._h = w, h

        to_discard = [
            sym for sym in list(self._alive)
            if _sym_pos(sym, my_core, w, h) != enemy_core
        ]
        for sym in to_discard:
            self._alive.discard(sym)

        self._try_confirm()

    def confirmed(self) -> bool:
        """True si la simetría ha sido determinada de forma inequívoca."""
        return self._confirmed is not None

    def get(self) -> Symmetry | None:
        """Simetría confirmada, o None si aún hay ambigüedad."""
        return self._confirmed

    def best_guess(self) -> Symmetry | None:
        """
        Mejor estimación aunque no esté confirmada.
        Orden de preferencia: ROTATIONAL > HORIZONTAL > VERTICAL.
        Devuelve None solo si no hay ninguna hipótesis viva (caso imposible
        en condiciones normales).
        """
        if self._confirmed is not None:
            return self._confirmed
        for pref in (Symmetry.ROTATIONAL, Symmetry.HORIZONTAL, Symmetry.VERTICAL):
            if pref in self._alive:
                return pref
        return None

    def candidates(self) -> list[Symmetry]:
        """
        Lista de hipótesis aún vivas, en orden canónico.
        Útil para explorar hacia todos los posibles cores enemigos mientras
        no se ha confirmado la simetría.
        """
        return [s for s in (Symmetry.HORIZONTAL, Symmetry.VERTICAL, Symmetry.ROTATIONAL)
                if s in self._alive]

    def symmetric_pos(self, pos: Position, w: int, h: int,
                      fallback: Symmetry | None = None) -> Position | None:
        """
        Posición simétrica de pos según la simetría confirmada.
        Si aún no está confirmada, usa fallback o best_guess().

        Uso típico para localizar el core enemigo:
            enemy_core_pos = MAP_SYM.symmetric_pos(my_core_pos, w, h)

        Devuelve None solo si no hay ninguna hipótesis viva.
        """
        sym = self._confirmed or fallback or self.best_guess()
        if sym is None:
            return None
        return _sym_pos(sym, pos, w, h)

    def all_symmetric_candidates(self, pos: Position,
                                  w: int, h: int) -> list[tuple[Symmetry, Position]]:
        """
        Posición simétrica de pos para cada hipótesis aún viva.

        Útil antes de la confirmación para enviar bots a explorar todos
        los posibles emplazamientos del core enemigo en paralelo.

        Returns:
            Lista de (Symmetry, Position) por cada candidato vivo.
        """
        return [(sym, _sym_pos(sym, pos, w, h)) for sym in self.candidates()]

    def is_alive(self, sym: Symmetry) -> bool:
        """True si la hipótesis sym sigue siendo candidata."""
        return sym in self._alive

    def reset(self) -> None:
        """Reinicio completo. En partidas normales no es necesario."""
        self._alive = {Symmetry.HORIZONTAL, Symmetry.VERTICAL, Symmetry.ROTATIONAL}
        self._terrain.clear()
        self._w = self._h = 0
        self._confirmed = None

    # ──────────────────────────────────────────────────────────────────────
    # Internos
    # ──────────────────────────────────────────────────────────────────────

    def _check_contradictions(self, pos: Position, env: Environment,
                               w: int, h: int) -> None:
        """
        Para cada hipótesis viva, mira si el tile simétrico de pos ya está
        cacheado con un entorno diferente. Si es así, descarta la hipótesis.
        """
        to_discard: list[Symmetry] = []
        for sym in list(self._alive):
            mirror = _sym_pos(sym, pos, w, h)
            if mirror == pos:
                # Tile sobre el eje de simetría: su simétrico es él mismo,
                # no aporta información para descartar
                continue
            mirror_env = self._terrain.get(mirror)
            if mirror_env is None:
                # Simétrico aún no observado: no podemos descartar todavía
                continue
            if mirror_env != env:
                to_discard.append(sym)

        for sym in to_discard:
            self._alive.discard(sym)

        self._try_confirm()

    def _try_confirm(self) -> None:
        """Marca como confirmada si solo queda una hipótesis."""
        if len(self._alive) == 1:
            self._confirmed = next(iter(self._alive))
        elif len(self._alive) == 0:
            # Inconsistencia en el mapa (no debería ocurrir): restaurar
            self._alive = {Symmetry.HORIZONTAL, Symmetry.VERTICAL, Symmetry.ROTATIONAL}

    def __repr__(self) -> str:
        if self._confirmed:
            return f"<MapSymmetry CONFIRMED={self._confirmed.value}>"
        return f"<MapSymmetry candidates={[s.value for s in self.candidates()]}>"