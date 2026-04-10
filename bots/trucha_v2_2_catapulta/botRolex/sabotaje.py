
from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position, ResourceType
import math
import bignav_a_mem as bugnav

from botRolex.helper.layout_defensivo import compute_layout_for_core
class Player:
    """
    Sentinel Hunter Bot
    -------------------
    Estrategia:
      1. Busca el sentinel enemigo más cercano en vision.
      2. Calcula su zona de ataque con get_attackable_tiles_from().
      3. Se posiciona en un tile seguro (fuera de esa zona) dentro del
         action radius (r²=2) del sentinel.
      4. Ataca con c.fire() hasta destruirlo.
      5. Solo busca el siguiente sentinel si está a FULL HP.
      6. Se repite infinitamente.
    """

    def __init__(self):
        self.target_id    = None   # ID del sentinel objetivo actual
        self.safe_pos     = None   # Posición segura desde la que atacar
        self.just_killed  = False  # Flag: acaba de destruir un sentinel

    # ─────────────────────────────────────────────
    #  LOOP PRINCIPAL
    # ─────────────────────────────────────────────
    def run(self, c: Controller):
        my_pos    = c.get_position()
        my_hp     = c.get_hp()
        my_max_hp = c.get_max_hp()

        # ── Regla de full HP ──────────────────────────────────────────────
        # Si acabamos de matar un sentinel, esperamos a recuperar vida completa
        # antes de ir a por el siguiente.
        if self.just_killed:
            if my_hp < my_max_hp:
                return          # Esperar (otro bot nos curación, o tiempo)
            self.just_killed  = False
            self.target_id    = None
            self.safe_pos     = None

        # ── Verificar que el objetivo actual sigue vivo ───────────────────
        if self.target_id is not None:
            if not self._entity_alive(c, self.target_id):
                # Lo hemos destruido (o ya no está visible)
                self.just_killed = True
                self.target_id   = None
                self.safe_pos    = None
                return          # Esperamos al siguiente turno para comprobar HP

        # ── Buscar objetivo si no tenemos uno ────────────────────────────
        if self.target_id is None:
            self.target_id = self._find_closest_enemy_sentinel(c)
            self.safe_pos  = None   # Recalcular posición segura

        if self.target_id is None:
            return  # No hay sentinels enemigos en vision, nada que hacer

        sentinel_pos = c.get_position(self.target_id)
        sentinel_dir = c.get_direction(self.target_id)

        # ── Calcular zona de peligro del sentinel ─────────────────────────
        danger_set = self._compute_danger_zone(c, sentinel_pos, sentinel_dir)

        # ── Calcular (o validar) posición segura de ataque ───────────────
        if self.safe_pos is None or not self._is_good_safe_pos(c, self.safe_pos, sentinel_pos, danger_set):
            self.safe_pos = self._find_safe_attack_pos(c, sentinel_pos, danger_set)

        # ── Atacar si estamos en posición (debemos buscar la fuente de la munición de la torreta) ─────────────────────────────────
        # Intentamos disparar: para un builder bot fire(target) usa el
        # ataque own-tile (daña el edificio en nuestra posición actual)
        # cuando estamos encima, o dentro del action radius si la API lo permite.

        if c.get_action_cooldown() == 0:
            # Primero intentamos disparar directamente al sentinel
            if c.can_fire(sentinel_pos):
                c.fire(sentinel_pos)
                return  
            # Alternativa: ataque own-tile (si estamos sobre él)
            if c.can_fire(my_pos):
                c.fire(my_pos)
                return

        # ── Moverse hacia la posición segura ─────────────────────────────
        if self.safe_pos is None:
            # Sin posición segura accesible: alejarse del peligro
            self._flee_danger(c, danger_set)
            return

        if c.get_move_cooldown() == 0:
            dist_to_safe = my_pos.distance_squared(self.safe_pos)
            if dist_to_safe > 0:
                self._move_toward(c, self.safe_pos, danger_set)

    # ─────────────────────────────────────────────
    #  HELPERS DE COMBATE
    # ─────────────────────────────────────────────

    def _find_closest_enemy_sentinel(self, c: Controller):
        """Devuelve el ID del sentinel enemigo más cercano visible, o None."""
        my_pos   = c.get_position()
        my_team  = c.get_team()
        best_id  = None
        best_d   = 10**9

        for eid in c.get_nearby_entities():
            try:
                if c.get_entity_type(eid) != EntityType.SENTINEL:
                    continue
                if c.get_team(eid) == my_team:
                    continue
                d = my_pos.distance_squared(c.get_position(eid))
                if d < best_d:
                    best_d  = d
                    best_id = eid
            except Exception:
                continue

        return best_id

    def _compute_danger_zone(self, c: Controller, sentinel_pos, sentinel_dir) -> set:
        """
        Devuelve un set de (x, y) con todos los tiles que el sentinel
        puede cubrir con su patrón de ataque (banda ±1 alrededor de su
        línea frontal, radio² = 32).
        """
        danger = set()
        try:
            tiles = c.get_attackable_tiles_from(
                sentinel_pos, sentinel_dir, EntityType.SENTINEL
            )
            for t in tiles:
                danger.add((t.x, t.y))
        except Exception:
            pass
        return danger

    def _find_safe_attack_pos(self, c: Controller, sentinel_pos, danger_set):
        """
        Busca un tile que cumpla:
          - Dentro del action radius del builder bot (r²=2) respecto al sentinel.
          - No está en la zona de peligro del sentinel.
          - Es pasable (o es nuestra posición actual).
        Devuelve un Position o None.
        """
        my_pos = c.get_position()

        # Action radius r²=2 → deltas: (0,±1), (±1,0), (±1,±1)
        # Ampliamos un poco la búsqueda (r²≤4) por si el r²=2 no basta
        for r2_limit in (2, 4):
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx * dx + dy * dy > r2_limit:
                        continue
                    candidate = Position(sentinel_pos.x + dx, sentinel_pos.y + dy)
                    if (candidate.x, candidate.y) in danger_set:
                        continue
                    if not c.is_in_vision(candidate):
                        continue
                    # ¿Es accesible?
                    if candidate == my_pos:
                        return candidate
                    if c.is_tile_passable(candidate):
                        return candidate

        return None  # No se encontró posición segura

    def _is_good_safe_pos(self, c: Controller, pos, sentinel_pos, danger_set) -> bool:
        """Verifica que la posición segura guardada sigue siendo válida."""
        if (pos.x, pos.y) in danger_set:
            return False
        if pos.distance_squared(sentinel_pos) > 4:
            return False
        if not c.is_in_vision(pos):
            return False
        return True

    def _entity_alive(self, c: Controller, eid: int) -> bool:
        """Comprueba si una entidad sigue viva y visible."""
        try:
            c.get_position(eid)
            return True
        except Exception:
            return False

    # ─────────────────────────────────────────────
    #  HELPERS DE MOVIMIENTO
    # ─────────────────────────────────────────────

    def _move_toward(self, c: Controller, target_pos, danger_set: set):
        """
        Mueve el bot un paso hacia target_pos.
        Prioriza el movimiento directo; si está bloqueado, prueba
        las direcciones adyacentes. Evita entrar en la zona de peligro.
        """
        my_pos   = c.get_position()
        main_dir = my_pos.direction_to(target_pos)

        # Lista de direcciones candidatas: directa → girar izq/der → otras
        candidates = [
            main_dir,
            main_dir.rotate_left(),
            main_dir.rotate_right(),
            main_dir.rotate_left().rotate_left(),
            main_dir.rotate_right().rotate_right(),
            main_dir.rotate_left().rotate_left().rotate_left(),
            main_dir.rotate_right().rotate_right().rotate_right(),
            main_dir.opposite(),
        ]

        for d in candidates:
            if d == Direction.CENTRE:
                continue
            new_pos = my_pos.add(d)
            if (new_pos.x, new_pos.y) in danger_set:
                continue       # Nunca moverse hacia el peligro
            if c.can_move(d):
                c.move(d)
                return

        # Si todas las opciones seguras fallan, mover en dirección principal
        # aunque haya peligro (último recurso)
        if c.can_move(main_dir):
            c.move(main_dir)

    def _flee_danger(self, c: Controller, danger_set: set):
        """Huye de la zona de peligro cuando no hay posición segura conocida."""
        my_pos = c.get_position()
        if (my_pos.x, my_pos.y) not in danger_set:
            return  # Ya estamos seguros

        if c.get_move_cooldown() != 0:
            return

        all_dirs = [
            Direction.NORTH, Direction.NORTHEAST, Direction.EAST,
            Direction.SOUTHEAST, Direction.SOUTH, Direction.SOUTHWEST,
            Direction.WEST, Direction.NORTHWEST,
        ]
        for d in all_dirs:
            new_pos = my_pos.add(d)
            if (new_pos.x, new_pos.y) not in danger_set and c.can_move(d):
                c.move(d)
                return