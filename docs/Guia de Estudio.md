# Guía de Estudio: Cambridge Battlecode 2026

¡Bienvenido al equipo! Esta guía está diseñada para ayudarte a entender rápidamente de qué trata la competición y cómo está estructurado el código de tus compañeros para que puedas ponerte al día y empezar a aportar lo antes posible.

---

## 1. Conceptos Básicos del Juego
El juego es una simulación por turnos que ocurre en un mapa de casillas (grid), donde el objetivo principal es **destruir el Core (núcleo) enemigo** o tener más puntos al final de la ronda 2000.

**Puntos Clave:**
- **Recursos:** Deberás extraer minerales en el mapa: **Titanio** y **Axionita**. Los "Harvesters" las extraen automáticamente.
- **Unidades Móviles:** Los **Builder Bots** son tus únicas unidades móviles. Construyen todo: harvesters, torretas, muros, etc.
- **Límites de Computación:** El juego es estricto; cada unidad tiene un máximo de **2 milisegundos (2ms)** por ronda para pensar. Si tu código es ineficiente, el turno de la unidad se cancela.
- **Sistema de Entidades:** Todo funciona mediante "IDs". Le pides al `Controller` (`ct`) información de una ID, en vez de usar objetos complejos en memoria, por un tema de rendimiento.

---

## 2. Documentación que DEBES leer (Carpeta `docs`)
El equipo tiene guardada la documentación. Te recomiendo leerlos en este orden:

1. 📄 **`Game Rules / Game Overview.md`**: El resumen general de las unidades, los stats, y las condiciones de victoria.
2. 📄 **`Game Rules / Resources.md`**: Cómo funciona el sistema de recursos y cintas transportadoras (conveyors).
3. 📄 **`Game Rules / Buildier Bot.md`**: Muy importante, ya que codificarás la lógica de estos bots móviles.
4. 📄 **`Game Rules / Turrets.md`**: Explica cómo defiende/ataca cada tipo de torreta (Sentinel, Breach, Launcher).
5. 📄 **`Getting Started / Running Matches.md`**: Para entender cómo levantar simulaciones en tu ordenador y probar el código de forma local.

---

## 3. Estado Actual del Código del Equipo
Actualmente, el equipo está trabajando en la versión **`camalar_v2.6`** dentro de la carpeta `bots`. 

### A. El punto de entrada (`main.py`)
Todo empieza en `bots/camalar_v2.6/main.py`. Aquí se encuentra la clase `Player`, que tiene la función `run(self, ct)` que se ejecuta todos los turnos por cada entidad. 
- En el `main.py`, usan un `ct.get_entity_type()` para saber qué tipo de unidad está ejecutando el código.
- Tienen un **sistema de cerebros ("brains")**. Según la ronda del juego, se asigna una clase cerebro diferente al bot.

### B. Sistema de Roles (`botRolex`)
El comportamiento de los Builder Bots es bastante avanzado. Usan distintas clases según la especialización del bot. Revisa la carpeta `botRolex/`:
- **`builder.py` / `Harvester`:** Es el archivo más importante (y grande). Parece tener la lógica base para recolectar, pathfinding básico o tomar recursos.
- **`defensivo.py`:** Se asigna a los bots en la Ronda 1. Su objetivo es colocar defensas iniciales.
- **`builderMuros3.py`:** Lógica enfocada en que el bot construya muros y protecciones. Se ve que han iterado a la versión 3.
- **`builderTorretas2.py`:** Lógica de un bot que está enfocado en colocar armamento defensivo/ofensivo.

### C. Torretas (`torretaRolex`)
Esta carpeta contiene el comportamiento específico que tendrán las torretas una vez construidas (`sentinel.py`, `breach.py`, `launcher.py`). Son más simples porque las torretas no se mueven.

### D. Navegación (`bignav_opus.py`)
En la raíz de la versión 2.6 hay un archivo grande llamado `bignav_opus.py`. Los juegos en grid requieren algoritmos de búsqueda y pathfinding para moverse eficientemente esquivando muros. Muy probablemente contenga los algoritmos de movimiento del equipo.

---

## 4. Plan de Acción Recomendado

1. **Lee la documentación oficial mínima:** (Game Overview y Builder Bot).
2. **Corre una partida:** Sigue el archivo `Running Matches.md` y observa visualmente cómo se comporta la versión `camalar_v2.6`. Entender el comportamiento viendo el juego te ahorrará horas de leer código a ciegas.
3. **Analiza el `main.py` de `camalar_v2.6`**: Entiende qué rol asigna el Core a los bots en los primeros 5 turnos.
4. **Habla con tu equipo:** Una vez visto lo básico, pregúntales: 
   - *"He visto que tenéis separados los roles en 'defensivo', 'muros', etc... ¿Qué rol es el más inestable ahora mismo?"*
   - *"¿Cómo funciona de forma general el bignav_opus.py para el pathfinding?"*
