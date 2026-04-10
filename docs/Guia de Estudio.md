````md
# 🧠 Battlecode 2026 – Mecánica de Salto de Muros Cooperativo

Actúa como un experto desarrollador de Python compitiendo en el torneo **Battlecode 2026**.

Nuestro objetivo es implementar una nueva mecánica de **"salto de muros" cooperativo** entre nuestros *Builder Bots* y el edificio *Launcher*, utilizando **Markers (marcadores)** para comunicarse, dado que los bots no comparten memoria global.

---

## ❗ Problema

Actualmente, en nuestro sistema de *pathfinding* (**BugNav / A\***), cuando el algoritmo detecta que el destino es inalcanzable caminando (por ejemplo, completamente bloqueado por muros), el bot se queda atascado.

---

## 💡 Solución

Queremos que el bot:

1. Construya una catapulta (*Launcher*).
2. Le "deje un mensaje" indicando a dónde debe lanzarlo.

---

## 🧩 División del trabajo

---

## 🔹 Parte 1: Builder Bot (Lógica de Navegación / BugNav)

Cuando el bot determine que **no puede llegar a su meta caminando**:

### 1. Buscar o construir un Launcher

- Comprobar si ya existe un *Launcher aliado adyacente*.
- Si no existe:
  - Buscar una casilla adyacente vacía.
  - Construirlo usando:

```python
c.build_launcher(pos)  # Coste: 20 Ti
````

---

### 2. Colocar un Marker con la meta

Si puede acceder a un Launcher (nuevo o existente):

* Colocar un marcador en una casilla adyacente al launcher y el bot espera en otra casilla adyacente al launcher:


* El `valor` codifica la posición objetivo:

```python
valor = goal.x * 1000 + goal.y
```

---

### 3. Esperar lanzamiento

* El bot finaliza su turno y espera a ser lanzado.

---

### 4. Manejo de recursos

* Si no puede construir el Launcher por falta de Titanio:

  * Movimiento aleatorio **o**
  * Continuar bordeando el muro

---

### 5. Consideraciones importantes

* Comprobar cooldowns:

  * `c.can_build_launcher(pos)`
  * `c.can_place_marker(pos)`
* Si hay estructuras propias en la casilla (ej. carreteras):

  * Probar a poner el launcher en otra posición donde pueda lanzar al bot a la casilla necesaria

  * Nunca eliminar estructuras propias para poner el launcher, si no que siga con:

  * Movimiento aleatorio **o**
  * Continuar bordeando el muro

---

## 🔹 Parte 2: Launcher (launcher.py)

En el método:

```python
def run(c):
```

Antes de atacar enemigos, debe priorizar ayudar a aliados.

---

### 1. Detectar bots atascados

* Obtener unidades cercanas:

```python
units = c.get_nearby_units(2)
```

* Filtrar:

  * Solo aliados
  * Solo *Builder Bots*

* Si encuentra un bot enemigo, tiene que lanzarlo lo mas lejano al core que pueda. Aunque debe priorizar ayudar a los aliados.

---

### 2. Detectar Marker al lado del launcher

* Para cada bot:

  * Comprobar si en una casilla adyacente al launcher hay un `MARKER` y un bot esperando

---

### 3. Decodificar objetivo

```python
valor = c.get_marker_value(marker_id)

goal_x = valor // 1000
goal_y = valor % 1000
```

* Luego de decodificar el `Marker`, el bot debe romper el marker con `c.destroy(marker_id)`
---

### 4. Calcular mejor destino de lanzamiento

* Obtener casillas posibles:

```python
tiles = c.get_nearby_tiles()
```

* Filtrar:

```python
c.can_launch(bot_pos, tile_pos)
```

---

### 5. Selección óptima

Elegir la casilla que:

* Minimice la distancia al objetivo
* Sea mejor que la posición actual

---

### 6. Lanzar

```python
c.launch(bot_pos, best_place)
```

---

## ⚠️ Requisitos clave

* Manejo correcto de cooldowns:

  * `c.can_place_marker`
  * `c.can_build_launcher`
* Evitar bloqueos del bot
* Comunicación robusta mediante encoding/decoding del marker

---

## ✅ Resultado esperado

* Los bots detectan cuando no pueden avanzar
* Construyen un Launcher si es necesario
* Señalizan su destino mediante Markers
* El Launcher interpreta la señal y los lanza estratégicamente
* Si no pueden ser lanzados, siguen con otro camino
