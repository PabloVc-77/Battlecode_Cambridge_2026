Bot Anti-Torretas Defensivo
Quiero crear un bot builder cuya misión exclusiva sea detectar y neutralizar torretas enemigas (Sentinel, Gunner, Breach, Launcher) que se encuentren cerca de nuestro Core (dentro de un radio determinado, que sea el máximo rango con el que una sentinel enemiga puede atacar a nuestro core).

Fase 1: Detección y análisis
El bot debe escanear las torretas enemigas visibles y analizar su fuente de alimentación, ya que las torretas (excepto Launcher) necesitan munición para disparar:

Comprobar las 4 casillas cardinales adyacentes a la torreta enemiga. Las torretas reciben munición desde cualquier dirección EXCEPTO la dirección a la que apuntan (las diagonales reciben por los 4 lados cardinales).

Clasificar la fuente de alimentación en uno de estos casos:

Caso A — Transporte: Un Conveyor, Armoured Conveyor (romper si es nuestro, si es enemigo se ignora), Splitter o Bridge aliado del enemigo que apunta su salida HACIA la torreta.
Caso B — Harvester: Un Harvester enemigo adyacente (cardinal) a la torreta, que le manda recursos directamente.
Caso C — Launcher: Los Launchers no usan munición, así que no tienen fuente de alimentación. Hay que actuar diferente.
Caso D — Sin fuente visible: La torreta puede tener la alimentación fuera de nuestro campo de visión, o estar almacenando munición. Tratar como Caso A pero atacando directamente la torreta.
Priorizar la torreta más peligrosa o más cercana al Core.

Fase 2: Neutralización (según el caso)
Caso A — Fuente de transporte (Conveyor/Splitter/Bridge):
Navegar hasta la casilla del elemento de transporte que alimenta a la torreta.
Posicionarse encima de ese elemento (los builders caminan sobre conveyors/bridges).
Usar fire() para destruirlo (2 daño/turno, pero sin riesgo de fuego enemigo si estamos fuera del rango de la torreta).
Una vez destruido, apartarse de la casilla (no se puede construir un Gunner con un bot encima).
Construir un Gunner apuntando a la torreta en la casilla donde estaba el elemento destruido.
El Gunner heredará la alimentación que antes iba a la torreta enemiga, recibirá munición y la destruirá automáticamente.
Caso B — Harvester adyacente:
Buscar la mejor casilla adyacente cardinal al Harvester donde se pueda construir un Gunner que alcance a la torreta (verificar con can_fire_from(pos, dir, EntityType.GUNNER, torreta_pos)).
Priorizar casillas vacías; si no hay, destruir roads o conveyors existentes.
Navegar a esa casilla, limpiarla si es necesario.
Apartarse y construir el Gunner apuntando a la torreta.
El bot debe quedarse cerca pero en zona segura (fuera del rango de ataque de la torreta) para poder reconstruir el Gunner si es destruido.
Si el Gunner es destruido antes de acabar con la torreta, reconstruirlo inmediatamente.
Caso C — Launcher (sin munición):
Los Launchers pueden lanzar nuestro builders lejos, así que hay que acercarse con cuidado.
Buscar una casilla adyacente al Launcher donde se pueda construir un Sentinel (tiene más rango y no necesita estar en línea recta).
Alternativamente, destruir el Launcher directamente posicionándose encima y usando fire() repetidamente (30 HP ÷ 2 daño = 15 turnos). El Launcher no hace daño directo, solo lanza.
Caso D — Sin fuente visible:
Buscar casilla adyacente a la torreta y construir un Gunner apuntando a ella.
Sin munición enemiga, la torreta dejará de disparar eventualmente.
Fase 3: Reparación post-combate
Una vez destruida la torreta enemiga:

Reconstruir la infraestructura rota — si destruimos un conveyor/splitter/bridge propio o enemigo que alimentaba a la torreta, ahora necesitamos restaurar el camino de recursos hacia nuestra base.
Si había un Harvester enemigo, construir conveyors desde esa zona hacia nuestro Core para robar los recursos.
Si la torreta destruyó algún elemento de nuestro layout defensivo (splitter, conveyor, foundry), reconstruirlo.
Volver al modo escaneo para buscar nuevas amenazas.
Consideraciones importantes
Seguridad del bot: No acercarse a casillas dentro del rango de ataque de la torreta enemiga si es posible evitarlo. Los Sentinels tienen r²=32 (muy lejos), los Gunners r²=13 y los Breach r²=5.
Persistencia: Si el bot muere, un nuevo bot spawneado debe poder reevaluar la situación desde cero.
Anti-stall: Si llevamos más de N turnos atacando sin reducir HP (porque el enemigo lo cura con un healer), cambiar de objetivo o buscar el healer.
Prioridad del Gunner construido: Un Gunner nuestro hace 10 daño/turno con 2 munición. Si hereda la alimentación del enemigo, destruirá la torreta en 3-4 turnos. Sin alimentación, no hará nada — asegurar que hay fuente de munición.