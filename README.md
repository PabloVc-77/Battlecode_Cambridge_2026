# 🤖 Battlecode Cambridge 2026

Bot desarrollado en Python para la competición **Battlecode Cambridge 2026**, un juego de estrategia en tiempo real por turnos donde dos equipos de bots compiten por controlar recursos y destruir el core enemigo.

---

## 📁 Estructura del proyecto

```
Battlecode_Cambridge_2026/
├── bots/
│   ├── Sprint_1/          # Versiones camalar v1.x
│   ├── Sprint_2/          # Versiones camalar v2.x
│   ├── Sprint_3/          # Versiones camalar v3.x + trucha v1.x
│   ├── trucha_v2_x/       # Versiones trucha v2.x (versión activa)
│   └── starter/           # Bot de ejemplo del juego
├── conductor/             # Herramientas y guías de estilo
├── docs/                  # Documentación de la API y reglas del juego
├── maps/                  # Mapas de prueba
├── pathFinders/           # Experimentos con algoritmos de navegación
└── some_other_code/       # Código auxiliar y experimentos
```

### Versión activa: `trucha_v2_8`

```
trucha_v2_8/
├── main.py                   # Punto de entrada — despacha por tipo de entidad
├── bignav_a_mem.py           # Motor de navegación (BugNav 4.0 + A* incremental)
├── map_symmetry.py           # Detector de simetría de mapa
├── botRolex/
│   ├── core.py               # Lógica del Core (spawn de bots, conversión de recursos)
│   ├── builder.py            # Bot recolector (Harvester) — construye rutas de recursos
│   ├── builderAtaque.py      # Bot atacante — destruye infraestructura enemiga
│   ├── defensivo.py          # Bot defensivo — construye el layout base alrededor del core
│   ├── healer.py             # Bot curador — repara aliados y contrarresta torretas
│   └── helper/
│       ├── layout_defensivo.py   # Definición y rotación del layout base
│       └── movement.py           # Helper de movimiento con gestión de barriers
└── torretaRolex/
    ├── gunner.py             # Torreta lineal de largo alcance
    ├── sentinel.py           # Torreta de área lateral
    ├── breach.py             # Torreta de área frontal (splash)
    └── launcher.py           # Lanzador de bots aliados/enemigos
```

---

## 🧠 Arquitectura y estrategia

### Roles de bots

El `main.py` asigna un rol a cada bot en su primer turno según la ronda actual y el contexto:

| Rol | Clase | Descripción |
|---|---|---|
| **Core** | `core.py` | Spawea bots, gestiona recursos y convierte axionita en titanio |
| **Defensivo** | `Defensivo` | Primer bot: construye el layout defensivo alrededor del core |
| **Harvester** | `Harvester` | Busca minerales, construye cadenas de puentes/conveyors hasta el core |
| **Atacante** | `Ataque` | Localiza infraestructura enemiga y coloca torretas en puntos clave |
| **Curador** | `Healer` | Repara edificios aliados y contrarresta torretas enemigas |

### Temporalización del spawn

```
Ronda 1  → Defensivo
Ronda 2–3 → Harvester
Ronda 4  → Atacante
Ronda 5–19 → Harvester
Ronda 20–69 → Healer
Ronda 70+ → 2/5 Healer, 2/5 Atacante, 1/5 Harvester
```

---

## 🗺️ Sistema de navegación — BugNav 4.0

Archivo: `bignav_a_mem.py`

Motor de navegación propio con cuatro capas:

### 1. A\* incremental multi-tick
- El A\* se ejecuta en background repartido entre turnos con un presupuesto de CPU (`CPU_BUDGET_US = 1000 µs`).
- Usa `c.get_cpu_time_elapsed()` para respetar el límite por tick.
- Mientras calcula, **BugNav cubre el movimiento** para que el bot nunca esté parado.

### 2. BugNav mejorado (Bug2)
- Wall-following con salida anticipada: el bot sale del perímetro en cuanto puede avanzar más hacia el goal que cuando chocó.
- Soporte para hand-switching (hasta 3 cambios) ante bucles detectados.

### 3. Mapa persistente
- `_map_passable` y `_map_blocked` sobreviven entre ticks.
- El A\* planifica rutas por zonas ya exploradas aunque estén fuera de visión.

### 4. Jumping Mechanic (launcher)
- Si A\* no encuentra camino, el bot busca un launcher adyacente aliado o construye uno.
- Codifica su destino en un marker (`NAV_MARKER_PREFIX + botID*10000 + x*100 + y`).
- El launcher lee el marker y lanza al bot hacia el destino.
- Anti-bucle: se registran las posiciones desde las que ya se saltó.

### 5. Opportunistic launch
- Si el bot pasa cerca de un launcher aliado y el goal está lejos, usa el launcher sin necesidad de que A\* haya fallado.

---

## 🏗️ Sistema de recursos — Harvester

Archivo: `botRolex/builder.py`

### Flujo de estados

```
Modo 0 → Buscar mineral (titanio o axionita)
Modo 1 → Colocar primer bridge junto al harvester
Modo 2 → Construir puentes hacia el core (bridgeHome)
Modo 3 → Verificar cadena existente (revisar_camino_casa)
Modo 4 → Colocar conveyors si son más baratos que bridges
Modo 5 → Defensa temporal con sentinel ante torreta enemiga
Modo 6 → Rastrear cadena rota hasta el harvester fuente
Modo 7 → Colocar barriers alrededor del harvester
```

### Características destacadas
- **Detección de cadenas rotas**: escanea nodos de transporte aliados cuyo output está vacío y retoma la construcción automáticamente.
- **Elección de puente vs conveyor**: calcula si una cadena de conveyors es más barata que un bridge antes de construir.
- **Rutas separadas por tipo de recurso**: titanio y axionita usan entradas distintas al core para evitar contaminación cruzada.
- **Markers de axionita** (`833xxyy`): marcan los bridges de rutas de axionita para identificarlas.

---

## 🔫 Torretas

### Gunner (`gunner.py`)
- Evalúa las 8 direcciones y rota hacia la que tenga el objetivo de mayor prioridad.
- No dispara a construcciones aliadas propias.

### Sentinel (`sentinel.py`)
- Dispara al primer objetivo enemigo visible en su banda lateral.
- Prioriza torretas enemigas > core > foundry > bots.

### Breach (`breach.py`)
- Disparo de área frontal (cono 180°, dist² ≤ 5).
- Apunta a adyacentes del core enemigo si este es el objetivo.

### Launcher (`launcher.py`)
- **Aliados**: lee markers NAV con el protocolo botID y lanza al bot al destino codificado.
- **Enemigos**: lanza bots enemigos adyacentes lo más lejos posible del core propio.
- Calcula el `semi_core` siguiendo la cadena de transporte para estimar qué es "lejos".

---

## 🧭 Detección de simetría — MapSymmetry

Archivo: `map_symmetry.py`

Detecta de forma incremental la simetría del mapa (horizontal, vertical o rotacional 180°) usando únicamente datos estáticos (muros, mineral) y la posición del core enemigo. Una vez confirmada, el atacante navega directamente al core enemigo estimado.

---

## 🛡️ Layout defensivo

Archivo: `botRolex/helper/layout_defensivo.py`

El layout base se coloca alrededor del core en una cuadrícula 5×5:
- **Splitters** en las 4 entradas diagonales (reciben recursos externos)
- **Conveyors** en los flancos laterales (3 por lado)
- **Foundries** en las entradas norte/sur (procesan axionita)
- **Barriers** en las esquinas

El sistema elige automáticamente la mejor rotación (R0, R_CW, R180, R_CCW) según el espacio disponible y la orientación hacia el centro del mapa.

---

## 🔧 Requisitos

- **Python 3.12**
- Entorno de Battlecode Cambridge 2026 (`cambc`)

---

## 🚀 Uso

Para ejecutar el bot en el entorno de Battlecode, apunta el runner al directorio de la versión activa:

```
bots/trucha_v2_8/
```

El punto de entrada es `main.py`, que implementa la clase `Player` requerida por el motor del juego.

---

## 📈 Historial de versiones

| Sprint | Versión | Notas |
|---|---|---|
| Sprint 1 | camalar v1.0 – v1.3 | Versiones iniciales |
| Sprint 2 | camalar v2.0 – v2.6 | Introducción de torretas |
| Sprint 3 | camalar v3.x / trucha v1.x | Nueva arquitectura de bots |
| — | trucha v2.0 – v2.8 | Versiones activas con BugNav 4.0 y jumping mechanic |

---

## 👥 Equipo

Proyecto universitario desarrollado en la **Universitat Politècnica de València (UPV)** — 3º Ingeniería Informática.
