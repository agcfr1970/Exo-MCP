# [Résolu] Serveur MCP Windows : dossier TP, Docker Desktop et variables d'environnement inaccessibles depuis OpenCode / llama3.2

**Type :** bug + feature
**Statut :** résolu
**Sévérité :** bloquante au départ (le serveur MCP ne démarrait pas), puis gêne fonctionnelle
**Composants :** `server.py`, `opencode.json`, OpenCode 2.3.2, Ollama 0.40.16, `llama3.2:latest`
**Environnement :** Windows 11, Python 3.14.4, projet `C:\users\public\ExoMCP`, profil utilisateur `C:\Users\orsys`

---

## 1. Contexte

L'objectif était de donner à un agent OpenCode la capacité d'exécuter trois actions locales sur
Windows, sans hook ni plugin :

1. ouvrir le dossier **TP** situé sur le Bureau ;
2. démarrer **Docker Desktop** ;
3. ouvrir directement la fenêtre des **variables d'environnement**.

Contraintes imposées :

- Windows uniquement ;
- **aucun hook / plugin** : tout doit passer par un serveur MCP stdio ;
- conserver **llama3.2** (pas de qwen) ;
- ne pas renommer les outils `ouvrir_dossier_tp` et `ouvrir_docker_desktop` ;
- l'agent ne doit réagir qu'à des phrases de déclenchement explicites et refuser le reste ;
- le Bureau réel est `C:\Users\orsys\Desktop`, alors que le projet vit dans
  `C:\users\public\ExoMCP` : cette séparation doit continuer de fonctionner.

---

## 2. Symptômes observés

### 2.1 Le serveur MCP ne démarre pas

```
IndentationError: expected an indented block after function definition on line 21
```

Le fichier `server.py` contenait une ligne `accueil = Path.home()` mal indentée à l'intérieur de
`chemin_accueil()`. OpenCode lançait le processus, qui mourait immédiatement : aucun outil
n'apparaissait.

### 2.2 Le dossier TP est introuvable

Une fois le serveur démarré, l'outil répondait :

```
Erreur : le dossier 'tp' n'existe pas sur le Bureau.
```

Alors que `C:\Users\orsys\Desktop\tp` existait bien.

### 2.3 Le modèle « écrit » l'appel au lieu de l'exécuter

Dans l'interface, llama3.2 affichait du JSON en clair :

```json
{"name": "ouvrir_dossier_tp", "arguments": {"nom_dossier": "tp"}}
```

mais aucune action n'était déclenchée. L'inspection de la session OpenCode montrait un message
assistant `type: "text"` avec `finish: "stop"` au lieu d'un `type: "tool"`.

### 2.4 Les outils MCP n'étaient pas visibles du modèle

Les outils étaient exposés via Code Mode (`execute`), ce qui empêchait llama3.2 de les voir comme
des outils natifs.

### 2.5 Après modification de `server.py`, rien ne change

Les corrections semblaient sans effet : le processus MCP déjà lancé continuait d'exécuter
l'ancienne version du fichier.

---

## 3. Analyse des causes racines

| # | Cause | Détail |
|---|---|---|
| 1 | **Erreur d'indentation** | `accueil = Path.home()` était aligné sur la signature de fonction au lieu d'être dans son corps. `Path.home()` n'était donc pas le vrai problème initial. |
| 2 | **Mauvais profil utilisateur** | OpenCode lançait le serveur MCP avec un environnement où `USERPROFILE` pointait vers `public` (répertoire du projet). `Path.home()` résolvait donc `C:\Users\public`, où il n'y a pas de Bureau `tp`. |
| 3 | **Prompt système trop long** | Un prompt détaillé (liste d'outils, JSON d'exemple, longues explications) poussait llama3.2 à recopier du JSON dans le texte. Les petits modèles suivent mieux une consigne courte et impérative. |
| 4 | **Code Mode activé** | Avec `codemode` par défaut, les outils MCP sont appelés indirectement via `execute`. Le modèle ne les perçoit pas comme des fonctions appelables. |
| 5 | **Processus MCP persistant** | OpenCode démarre le serveur MCP une seule fois par session. Modifier `server.py` ou `opencode.json` ne provoque pas de respawn automatique. |
| 6 | **Liste blanche incomplète** | Les permissions autorisaient un ancien nom d'outil (`actions_bouger_souris_et_ouvrir_dossier`) au lieu des noms réellement exposés. |

---

## 4. Résolution

### 4.1 Réécriture propre de `server.py`

- Docstring de module, imports explicites (`os`, `subprocess`, `sys`, `pathlib`).
- `chemin_accueil()` avec cascade : `USERPROFILE` → `Path.home()` → `HOMEDRIVE` + `HOMEPATH`.
- `chemins_bureau()` : registre `User Shell Folders` en priorité, puis `Desktop`, `OneDrive\Desktop`,
  `OneDrive\Bureau`, `Bureau`.
- `trouver_dossier_bureau()` : nettoyage des guillemets et repli mot par mot quand le modèle envoie
  la phrase entière.
- `chemin_docker_desktop()` : trois emplacements d'installation standard.
- `lancer()` : `os.startfile` avec repli `subprocess.Popen`.
- Trois outils exposés avec des noms stables :
  - `ouvrir_dossier_tp`
  - `ouvrir_docker_desktop`
  - `ouvrir_variables_environnement`

### 4.2 Correction du profil utilisateur

Dans `opencode.json`, le bloc MCP injecte désormais :

```json
"environment": {
  "USERPROFILE": "C:\\Users\\orsys",
  "HOMEDRIVE": "C:",
  "HOMEPATH": "\\Users\\orsys"
}
```

Ainsi, même si OpenCode est lancé depuis `C:\users\public\ExoMCP`, le serveur voit le bon Bureau.

### 4.3 Prompt système court

Le prompt est réduit à trois règles d'association et une consigne anti-JSON :

> Tu disposes de trois outils. Demande sur Docker : appelle `actions_ouvrir_docker_desktop`.
> Demande sur le dossier TP : appelle `actions_ouvrir_dossier_tp` avec `nom_dossier='tp'`.
> Demande sur les variables d'environnement : appelle `actions_ouvrir_variables_environnement`.
> Pour toute autre demande, réponds exactement : Je ne peux pas répondre à cette demande.
> N'écris jamais de JSON en texte : utilise toujours un appel d'outil.

Validé par un test direct contre Ollama : 4/4 phrases de déclenchement produisent de vrais
`tool_calls` (`ouvre docker`, `ouvre docker desktop`, `lance docker desktop`, phrase TP).

### 4.4 Désactivation de Code Mode

```json
"codemode": false
```

Les outils MCP sont exposés directement, sans passer par `execute`.

### 4.5 Liste blanche stricte des permissions

Tous les outils intégrés sont refusés (`execute`, `shell`, `read`, `edit`, `glob`, `grep`,
`subagent`, `skill`, `question`, `webfetch`, `websearch`, `experimental_image_generate`).
Seuls les trois outils MCP sont autorisés.

### 4.6 Nouvelle action « variables d'environnement »

Commande retenue :

```powershell
rundll32.exe C:\Windows\System32\sysdm.cpl,EditEnvironmentVariables
```

- Lancement non bloquant via `subprocess.Popen(..., close_fds=True)`.
- Vérification préalable de l'existence de `rundll32.exe` et `sysdm.cpl`.
- Repli sur `SystemPropertiesAdvanced.exe` si nécessaire.
- Message de succès explicite, erreurs tracées sur `stderr`.

---

## 5. Validation

| Vérification | Résultat |
|---|---|
| `python -m py_compile server.py` | OK |
| `opencode debug config --standalone` | OK (JSON strict sans commentaires, 3 permissions `actions_*`) |
| Client MCP réel (`list_tools`) | `['ouvrir_dossier_tp', 'ouvrir_docker_desktop', 'ouvrir_variables_environnement']` |
| Appel réel `ouvrir_variables_environnement` | `OK : la fenêtre des variables d'environnement est ouverte.` |
| Fenêtre Windows détectée (`EnumWindows`) | Classe `#32770`, titre **« Variables d'environnement »** |
| Dossier TP | `C:\Users\orsys\Desktop\tp` ouvert |
| Docker Desktop | `C:\Program Files\Docker\Docker\Docker Desktop.exe` détecté et lancé |
| Test Ollama (prompt court) | 4/4 `tool_calls` réels |

---

## 6. Prévention / bonnes pratiques

1. **Toujours** valider `py_compile server.py` après une édition : une erreur d'indentation tue le
   serveur silencieusement côté OpenCode.
2. **Reconnecter** le serveur MCP après toute modification :
   `/mcps` → `actions` → disconnect → reconnect (ou `opencode reload`).
3. **Ne pas allonger le prompt système** : pour llama3.2, la concision est une fonctionnalité.
4. **Garder `codemode: false`** tant que l'on veut des outils MCP directs.
5. **Écrire les erreurs sur `stderr`**, jamais sur `stdout` : `stdout` est le canal du protocole MCP.
6. **Vérifier les noms d'outils** dans les permissions : ils incluent le préfixe du serveur
   (`actions_`).
7. **Ne pas commenter `opencode.json`** : le JSON standard interdit les commentaires. La version
   pédagogique vit dans `opencode.annote.jsonc`, qui n'est jamais chargé.
8. En cas de doute sur une régression, **réécrire le fichier en entier** plutôt que d'appliquer un
   patch partiel : des retours arrière partiels ont été observés pendant le débogage.

---

## 7. Suivi / pistes d'amélioration

- [ ] Ajouter un test automatisé (`pytest` + client MCP) pour les trois outils.
- [ ] Rendre le chemin du venv configurable via une variable d'environnement.
- [ ] Supprimer ou rendre optionnel le `pyautogui.moveTo(500, 500)`.
- [ ] Ajouter un outil « ouvrir un dossier du Bureau par nom » générique.
- [ ] Documenter une procédure de packaging (`.zip` + script d'installation).
- [ ] Vérifier le comportement sur une machine sans Docker Desktop installé.
