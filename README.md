# ExoMCP — serveur MCP d'actions Windows pour OpenCode

> Un serveur MCP local (stdio) qui donne à un agent OpenCode trois actions concrètes sur Windows :
> ouvrir le dossier **TP** du Bureau, démarrer **Docker Desktop** et ouvrir la fenêtre des
> **variables d'environnement**.

Le projet est volontairement minimal : **un seul fichier Python** (`server.py`), **une seule
configuration OpenCode** (`opencode.json`), **aucun hook ni plugin**. L'agent ne peut rien faire
d'autre que ces trois actions : tous les outils intégrés d'OpenCode sont refusés.

---

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration OpenCode](#configuration-opencode)
- [Utilisation](#utilisation)
- [Détail des outils](#détail-des-outils)
- [Tests et validation](#tests-et-validation)
- [Dépannage](#dépannage)
- [Structure du projet](#structure-du-projet)
- [Limites connues](#limites-connues)

---

## Fonctionnalités

| Outil MCP | Nom exposé dans OpenCode | Paramètre | Effet |
|---|---|---|---|
| `ouvrir_dossier_tp` | `actions_ouvrir_dossier_tp` | `nom_dossier: str` | Déplace la souris puis ouvre le dossier du Bureau (ex. `tp`) dans l'Explorateur |
| `ouvrir_docker_desktop` | `actions_ouvrir_docker_desktop` | — | Démarre `Docker Desktop.exe` |
| `ouvrir_variables_environnement` | `actions_ouvrir_variables_environnement` | — | Ouvre directement la boîte de dialogue **Variables d'environnement** de Windows |

Chaque outil renvoie une chaîne courte en français : `OK : ...` en cas de succès, `Erreur : ...`
sinon. Ce texte est réinjecté dans la conversation, ce qui rend le résultat lisible par
l'utilisateur et exploitable par le modèle.

---

## Architecture

```
┌──────────────────────┐        stdio (JSON-RPC MCP)        ┌────────────────────────────┐
│  OpenCode (agent     │  ───────────────────────────────▶  │  server.py                 │
│  « exo », llama3.2)  │  ◀───────────────────────────────  │  MCPServer("actions")      │
└──────────┬───────────┘         tools / results            └─────────────┬──────────────┘
           │                                                              │
           │ prompt système court + permissions                           │ appels Windows
           ▼                                                              ▼
   ollama/llama3.2:latest                                  Explorateur, Docker Desktop,
   (décide QUEL outil appeler)                             rundll32.exe sysdm.cpl
```

Points clés :

- **Transport stdio** : OpenCode lance `python.exe server.py` et dialogue via `stdin`/`stdout`.
  Toute sortie de debug doit donc aller sur `stderr` (c'est ce que fait `server.py`).
- **Préfixage** : le serveur s'appelle `actions`, donc l'outil `ouvrir_dossier_tp` devient
  `actions_ouvrir_dossier_tp` dans les permissions OpenCode.
- **`codemode: false`** : les outils MCP sont exposés directement au modèle, sans passer par
  l'outil `execute` de Code Mode. C'est indispensable pour que llama3.2 les voie comme de vrais
  outils.

---

## Prérequis

| Composant | Version testée | Remarque |
|---|---|---|
| Windows | 11 | Le serveur utilise `winreg`, `os.startfile`, `rundll32.exe` |
| Python | 3.14.4 | Le venv du projet embarque les dépendances |
| `mcp` (SDK Python) | 2.3.0 | Fournit `mcp.server.mcpserver.MCPServer` |
| `PyAutoGUI` | 0.9.54 | Uniquement pour le déplacement du curseur |
| OpenCode | 2.3.2 | `opencode.json` en JSON strict, annotations dans `opencode.annote.jsonc` |
| Ollama | 0.40.16 | Modèle `llama3.2:latest` avec capacité `tools` |
| Docker Desktop | installé | Chemin détecté automatiquement |

---

## Installation

```powershell
# 1. Se placer dans le projet
cd C:\users\public\ExoMCP

# 2. Créer le venv (déjà présent dans ce dépôt)
py -3.14 -m venv .venv

# 3. Installer les dépendances
.\.venv\Scripts\python.exe -m pip install "mcp[cli]" pyautogui

# 4. Vérifier que le serveur démarre
.\.venv\Scripts\python.exe -m py_compile server.py
```

Le venv est référencé **en dur** dans `opencode.json`. Si tu déplaces le projet, mets à jour le
champ `command`.

---

## Configuration OpenCode

Le fichier `opencode.json` contient trois blocs :

### 1. Le modèle par défaut

```json
"model": "ollama/llama3.2:latest",
"default_agent": "exo"
```

llama3.2 est conservé volontairement : il est local, rapide et suffisant pour choisir entre trois
outils, à condition que le prompt système reste **court**.

### 2. Le serveur MCP

```json
"mcp": {
  "servers": {
    "actions": {
      "type": "local",
      "command": [
        "C:\\Users\\public\\ExoMCP\\.venv\\Scripts\\python.exe",
        "C:\\Users\\public\\ExoMCP\\server.py"
      ],
      "environment": {
        "USERPROFILE": "C:\\Users\\orsys",
        "HOMEDRIVE": "C:",
        "HOMEPATH": "\\Users\\orsys"
      },
      "codemode": false
    }
  }
}
```

**Pourquoi les variables d'environnement ?** Le projet vit dans `C:\users\public\ExoMCP`, mais le
Bureau réel de l'utilisateur est dans `C:\Users\orsys\Desktop`. Si OpenCode démarre le serveur avec
le profil `public`, `Path.home()` pointe au mauvais endroit et le dossier `tp` est introuvable. En
forçant `USERPROFILE`, `HOMEDRIVE` et `HOMEPATH`, le serveur voit toujours le bon profil — quel que
soit le répertoire de lancement. `server.py` conserve malgré tout une cascade de replis
(`USERPROFILE` → `Path.home()` → `HOMEDRIVE` + `HOMEPATH`).

### 3. L'agent `exo`

```json
"agents": {
  "exo": {
    "mode": "primary",
    "model": "ollama/llama3.2:latest",
    "system": "Tu disposes de trois outils. ...",
    "permissions": [ ... ]
  }
}
```

Le prompt système est **volontairement court et impératif**. Un prompt long ou contenant du JSON
littéral pousse llama3.2 à recopier du JSON dans sa réponse texte au lieu d'émettre un vrai
`tool_call`. La consigne « N'écris jamais de JSON en texte » est essentielle.

Les permissions appliquent une liste blanche stricte :

- `deny` sur `execute`, `shell`, `read`, `edit`, `glob`, `grep`, `subagent`, `skill`, `question`,
  `webfetch`, `websearch`, `experimental_image_generate` ;
- `allow` uniquement sur les trois actions MCP.

Résultat : même si le modèle hallucine un autre outil, OpenCode le refuse.

> **Commentaires** : le format JSON standard **n'autorise pas** les commentaires. `opencode.json`
> reste donc du JSON strict, sans aucun `//` ni `/* */`. La version commentée ligne par ligne est
> fournie à part dans **`opencode.annote.jsonc`** : c'est uniquement de la documentation, ce fichier
> n'est jamais chargé par OpenCode. Si tu modifies la configuration, reporte le changement dans les
> deux fichiers.

---

## Utilisation

Lance OpenCode dans le projet, puis écris simplement :

| Demande | Outil déclenché |
|---|---|
| « ouvre le dossier TP » / « ouvre tp sur le bureau » | `actions_ouvrir_dossier_tp` avec `nom_dossier="tp"` |
| « ouvre Docker » / « lance Docker Desktop » | `actions_ouvrir_docker_desktop` |
| « ouvre les variables d'environnement » | `actions_ouvrir_variables_environnement` |

Toute autre demande reçoit la réponse fixe :

> Je ne peux pas répondre à cette demande.

C'est le comportement attendu : l'agent est un exécutant, pas un assistant généraliste.

---

## Détail des outils

### `ouvrir_dossier_tp(nom_dossier)`

1. Nettoie le nom (espaces, guillemets).
2. Si le modèle a envoyé une phrase entière (« ouvre le dossier tp sur le bureau »), chaque mot est
   essayé comme nom de dossier.
3. Cherche dans tous les Bureaux possibles, dans cet ordre :
   - valeur `Desktop` du registre `User Shell Folders` (source de vérité Windows) ;
   - `%USERPROFILE%\Desktop` ;
   - `%USERPROFILE%\OneDrive\Desktop` ;
   - `%USERPROFILE%\OneDrive\Bureau` ;
   - `%USERPROFILE%\Bureau`.
4. Déplace la souris en `(500, 500)` — purement cosmétique, l'échec est ignoré.
5. Ouvre le dossier via `os.startfile`.

### `ouvrir_docker_desktop()`

Cherche `Docker Desktop.exe` dans :

- `%ProgramFiles%\Docker\Docker\Docker Desktop.exe`
- `%ProgramFiles(x86)%\Docker\Docker\Docker Desktop.exe`
- `%LOCALAPPDATA%\Docker\Docker Desktop.exe`

Puis le lance avec `os.startfile`.

### `ouvrir_variables_environnement()`

Commande principale :

```powershell
rundll32.exe C:\Windows\System32\sysdm.cpl,EditEnvironmentVariables
```

C'est le point d'entrée officieux de Windows pour ouvrir **directement** la boîte de dialogue
« Variables d'environnement », sans passer par les propriétés système. Elle est lancée avec
`subprocess.Popen` (non bloquant), donc la fenêtre reste ouverte quand le serveur MCP continue de
tourner.

Repli si `rundll32.exe` ou `sysdm.cpl` est absent : lancement de
`SystemPropertiesAdvanced.exe` (onglet « Paramètres système avancés »), avec un message invitant à
cliquer sur « Variables d'environnement ».

---

## Tests et validation

### 1. Syntaxe et configuration

```powershell
.\.venv\Scripts\python.exe -m py_compile server.py
opencode debug config --standalone
```

La seconde commande doit lister `C:\users\public\ExoMCP\opencode.json` avec les trois permissions
`actions_*` et le bloc MCP.

### 2. Test MCP réel (sans passer par le modèle)

```python
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=[r"C:\users\public\ExoMCP\server.py"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])
            out = await session.call_tool("ouvrir_variables_environnement", {})
            print(out.content[0].text)

asyncio.run(main())
```

Sortie attendue :

```
['ouvrir_dossier_tp', 'ouvrir_docker_desktop', 'ouvrir_variables_environnement']
OK : la fenêtre des variables d'environnement est ouverte.
```

### 3. Vérifier que la fenêtre est réellement ouverte

`Get-Process | Where-Object MainWindowTitle` ne suffit pas : les boîtes de dialogue Win32 ne sont
pas toujours exposées comme fenêtre principale. Utilise `EnumWindows` (classe `#32770`) ou vérifie
visuellement la fenêtre **« Variables d'environnement »**.

### 4. Test du modèle (tool_call réel)

Le critère de succès n'est pas le texte affiché, mais la présence d'un message assistant de
`type: "tool"` dans la session OpenCode. Un message `type: "text"` contenant du JSON signifie que
le modèle a « écrit » l'appel au lieu de l'émettre.

---

## Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| Le nouvel outil n'apparaît pas | Le processus MCP est lancé une fois et ne se recharge pas | `/mcps` → `actions` → disconnect puis reconnect (ou `opencode reload`) |
| `Le dossier 'tp' n'existe pas` | `USERPROFILE` pointe vers `public` | Vérifier le bloc `environment` de `opencode.json` |
| Le modèle répond du JSON en texte | Prompt système trop long / trop explicatif | Garder le prompt court et impératif |
| Aucune fenêtre ne s'ouvre | Session sans bureau interactif / droits | Lancer OpenCode dans la session utilisateur normale |
| `Docker Desktop n'est pas installé` | Chemin non standard | Ajouter le chemin dans `chemin_docker_desktop()` |
| Le serveur MCP ne démarre pas | Dépendance manquante ou mauvais interpréteur | Tester `python.exe server.py` et lire `stderr` |
| `IndentationError` au démarrage | Fichier édité partiellement | `py_compile server.py` avant de recharger |

---

## Structure du projet

```
C:\users\public\ExoMCP\
├── .venv\                  # Environnement Python (mcp, pyautogui)
├── server.py               # Serveur MCP (3 outils) — commenté ligne par ligne
├── opencode.json           # Configuration OpenCode active (JSON strict, sans commentaires)
├── opencode.annote.jsonc   # Copie documentaire commentée ligne par ligne (non chargée)
├── README.md               # Ce document
└── ISSUE.md                # Rétrospective / rapport d'incident du projet
```

---

## Limites connues

- **Windows uniquement** : `winreg`, `os.startfile`, `rundll32.exe`, `sysdm.cpl`.
- **Pas de hook ni de plugin** : tout passe par le serveur MCP, conformément à la demande.
- **Pas de confirmation utilisateur** : les actions s'exécutent dès que le modèle émet le
  `tool_call`. Le périmètre est limité par la liste blanche de permissions.
- **Déplacement de souris** : `pyautogui.moveTo(500, 500)` est un effet visuel hérité ; il peut
  surprendre. Il est sans impact fonctionnel et peut être retiré sans risque.
- **Détection de Docker** : basée sur les chemins d'installation standard ; une installation
  personnalisée nécessite d'ajouter un candidat.
- **Pas de tests automatisés** dans le dépôt : les validations sont des scripts ponctuels
  (voir [Tests et validation](#tests-et-validation)).
