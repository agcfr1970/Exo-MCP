"""Serveur MCP d'actions Windows (Bureau, Docker, variables d'environnement)."""  # Docstring du module : résume le rôle du fichier pour l'outil et pour les humains.

import os  # Fournit os.environ (variables d'environnement) et os.startfile (ouverture Windows).
import subprocess  # Permet de démarrer un programme externe, ici rundll32.exe, sans bloquer.
import sys  # Donne accès à sys.stderr pour journaliser les erreurs hors du canal MCP (stdout).
from pathlib import Path  # Représente les chemins de fichiers de façon portable et lisible.

import pyautogui  # Bibliothèque qui déplace le curseur de la souris (petit effet visuel).

from mcp.server.mcpserver import MCPServer  # Classe du SDK MCP qui transforme des fonctions en outils.

mcp = MCPServer("actions")  # Instancie le serveur MCP nommé "actions" (les outils deviennent actions_*).


def chemin_accueil() -> Path:  # Utilitaire : détermine le dossier personnel de l'utilisateur Windows.
    """Retourne le dossier personnel, même si les variables d'environnement sont absentes."""  # Docstring affichée par les outils d'introspection Python.
    userprofile = os.environ.get("USERPROFILE")  # Lit la variable Windows standard du profil utilisateur.
    if userprofile:  # Cas normal : USERPROFILE existe et n'est pas vide.
        return Path(userprofile)  # On renvoie directement ce chemin, sans autre calcul.

    try:  # Deuxième tentative : laisser Python deviner le dossier personnel.
        return Path.home()  # Path.home() utilise USERPROFILE ou HOMEDRIVE/HOMEPATH.
    except (RuntimeError, OSError):  # Path.home() peut échouer si aucune variable n'est définie.
        pass  # On ignore l'erreur et on tente la méthode manuelle ci-dessous.

    homedrive = os.environ.get("HOMEDRIVE", "")  # Récupère la lettre de lecteur (ex. "C:"), sinon vide.
    homepath = os.environ.get("HOMEPATH", "")  # Récupère le chemin du profil (ex. "\Users\orsys").
    if homedrive and homepath:  # Les deux moitiés sont nécessaires pour reconstruire le chemin.
        return Path(homedrive + homepath)  # Recompose "C:" + "\Users\orsys" en un chemin valide.

    raise RuntimeError("Impossible de déterminer le dossier personnel (USERPROFILE absent).")  # Dernier recours : erreur explicite.


def chemins_bureau() -> list[Path]:  # Utilitaire : liste tous les emplacements possibles du Bureau.
    """Liste les emplacements possibles du Bureau, en priorisant celui déclaré par Windows."""  # Docstring : ordre de priorité documenté.
    chemins: list[Path] = []  # Accumulateur des candidats, dans l'ordre de priorité.

    if os.name == "nt":  # Le registre Windows n'existe que sur Windows (garde-fou).
        try:  # L'accès au registre peut échouer (droits, clé absente) : on protège.
            import winreg  # Import local : ce module n'existe que sur Windows.

            with winreg.OpenKey(  # Ouvre la clé qui stocke les dossiers spéciaux de l'utilisateur.
                winreg.HKEY_CURRENT_USER,  # Ruche du profil de l'utilisateur courant.
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",  # Chemin de la clé.
            ) as cle:  # Ferme automatiquement la clé à la fin du bloc.
                valeur, _ = winreg.QueryValueEx(cle, "Desktop")  # Lit la valeur "Desktop" (peut contenir %USERPROFILE%).
                chemins.append(Path(os.path.expandvars(valeur)))  # Développe les variables puis ajoute le chemin.
        except OSError:  # Clé inaccessible ou valeur absente : ce n'est pas bloquant.
            # Clé absente ou inaccessible : on se rabat sur les chemins connus.
            pass  # On continue avec les chemins calculés plus bas.

    accueil = chemin_accueil()  # Récupère le dossier personnel via la fonction dédiée.
    chemins.extend(  # Ajoute les emplacements classiques du Bureau, dans l'ordre de probabilité.
        (  # Début du tuple de candidats.
            accueil / "Desktop",  # Bureau standard anglophone.
            accueil / "OneDrive" / "Desktop",  # Bureau synchronisé OneDrive (anglais).
            accueil / "OneDrive" / "Bureau",  # Bureau synchronisé OneDrive (français).
            accueil / "Bureau",  # Bureau standard francophone.
        )  # Fin du tuple.
    )  # Fin de l'ajout.

    uniques: list[Path] = []  # Liste finale sans doublons, tout en gardant l'ordre.
    for chemin in chemins:  # Parcourt chaque candidat dans l'ordre de priorité.
        if chemin not in uniques:  # Évite d'ajouter deux fois le même chemin.
            uniques.append(chemin)  # Conserve le candidat unique.
    return uniques  # Renvoie la liste dédupliquée.


def trouver_dossier_bureau(nom_dossier: str) -> Path | None:  # Cherche un dossier précis sur le Bureau.
    """Retourne le dossier du Bureau portant le nom demandé, ou None."""  # Docstring : None signifie "introuvable".
    nom_dossier = nom_dossier.strip().strip('"').strip("'")  # Nettoie espaces et guillemets autour du nom.
    candidats = [nom_dossier]  # Premier essai : le nom exact fourni par le modèle.
    # llama3.2 renvoie parfois la phrase entière au lieu du nom du dossier.
    if " " in nom_dossier:  # Si le modèle a envoyé une phrase au lieu d'un simple nom.
        candidats.extend(nom_dossier.split())  # Ajoute chaque mot comme candidat de secours.

    for candidat in candidats:  # Teste les candidats du plus précis au plus large.
        for bureau in chemins_bureau():  # Teste chaque emplacement de Bureau connu.
            cible = bureau / candidat  # Construit le chemin candidat.
            if cible.is_dir():  # Vérifie que c'est bien un dossier existant.
                return cible  # Premier dossier trouvé : on le renvoie immédiatement.
    return None  # Aucun candidat n'existe : signal d'échec pour l'appelant.


def chemin_docker_desktop() -> Path | None:  # Localise l'exécutable de Docker Desktop.
    """Retourne l'exécutable de Docker Desktop, ou None s'il n'est pas installé."""  # Docstring : None = non installé.
    programme = os.environ.get("ProgramFiles", r"C:\Program Files")  # Dossier "Program Files" (64 bits).
    programme_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")  # Dossier "Program Files (x86)".
    local = os.environ.get("LOCALAPPDATA", "")  # Dossier local de l'utilisateur (installation par utilisateur).

    candidats = [  # Liste des emplacements d'installation connus de Docker Desktop.
        Path(programme) / "Docker" / "Docker" / "Docker Desktop.exe",  # Installation standard 64 bits.
        Path(programme_x86) / "Docker" / "Docker" / "Docker Desktop.exe",  # Ancienne installation 32 bits.
    ]  # Fin de la liste de base.
    if local:  # LOCALAPPDATA peut être absent dans un environnement minimal.
        candidats.append(Path(local) / "Docker" / "Docker Desktop.exe")  # Ajoute l'installation par utilisateur.

    for candidat in candidats:  # Parcourt les emplacements dans l'ordre de priorité.
        if candidat.is_file():  # Vérifie que l'exécutable existe réellement.
            return candidat  # Renvoie le premier exécutable trouvé.
    return None  # Docker Desktop n'est installé à aucun emplacement connu.


def dossier_systeme() -> Path:  # Utilitaire : localise le dossier système Windows (System32).
    """Retourne le dossier System32 de Windows."""  # Docstring : chemin attendu des binaires système.
    system_root = os.environ.get("SystemRoot", r"C:\Windows")  # Lit SystemRoot, avec repli sur C:\Windows.
    return Path(system_root) / "System32"  # Construit le chemin complet de System32.


def lancer(chemin: Path) -> None:  # Utilitaire : ouvre un fichier ou un exécutable avec Windows.
    """Ouvre un fichier ou un exécutable avec le programme associé de Windows."""  # Docstring : comportement type double-clic.
    if hasattr(os, "startfile"):  # os.startfile n'existe que sous Windows.
        os.startfile(str(chemin))  # type: ignore[attr-defined]  # Ouvre le chemin avec l'association Windows.
        return  # startfile ne rend pas la main : on s'arrête là.

    subprocess.Popen([str(chemin)])  # Repli hors Windows ou si startfile est absent.


@mcp.tool(  # Décorateur : expose la fonction suivante comme outil MCP.
    name="ouvrir_dossier_tp",  # Nom exact de l'outil côté OpenCode (préfixé par "actions_").
    description="Ouvre le dossier TP situé sur le Bureau de Windows.",  # Description lue par le modèle pour choisir l'outil.
)  # Fin de la configuration du décorateur.
def ouvrir_dossier_tp(nom_dossier: str) -> str:  # Outil n°1 : ouvre le dossier TP du Bureau.
    """Déplace le curseur de la souris puis ouvre le dossier TP du Bureau."""  # Docstring interne de la fonction.
    dossier = trouver_dossier_bureau(nom_dossier)  # Résout le nom reçu vers un vrai dossier du Bureau.
    if dossier is None:  # Cas d'échec : le dossier demandé n'existe pas.
        return f"Erreur : le dossier '{nom_dossier}' n'existe pas sur le Bureau."  # Message clair renvoyé au modèle.

    try:  # Le déplacement de souris est purement cosmétique : il ne doit jamais bloquer l'action.
        pyautogui.moveTo(500, 500, duration=0.5)  # Déplace le curseur au centre de l'écran en une demi-seconde.
    except Exception as erreur:  # Session sans écran, FAILSAFE, permissions : on ignore l'échec.
        # Session sans affichage, FAILSAFE, etc. : on ouvre quand même le dossier.
        print(f"[souris] {erreur}", file=sys.stderr)  # Trace l'erreur sur stderr sans polluer stdout (protocole MCP).

    try:  # L'ouverture du dossier peut échouer (droits, chemin invalide).
        lancer(dossier)  # Ouvre le dossier dans l'Explorateur Windows.
    except OSError as erreur:  # Erreur système lors de l'ouverture.
        return f"Erreur : impossible d'ouvrir '{dossier}' : {erreur}"  # Message d'erreur détaillé.

    return f"OK : dossier '{dossier}' ouvert."  # Confirmation avec le chemin réellement ouvert.


@mcp.tool(name="ouvrir_docker_desktop", description="Démarre Docker Desktop sur Windows.")  # Outil n°2 : démarre Docker Desktop.
def ouvrir_docker_desktop() -> str:  # Fonction sans paramètre : une seule action possible.
    """Lance Docker Desktop."""  # Docstring interne de la fonction.
    executable = chemin_docker_desktop()  # Localise l'exécutable sur le disque.
    if executable is None:  # Docker Desktop n'est pas installé.
        return "Erreur : Docker Desktop n'est pas installé sur cette machine."  # Message explicite pour l'utilisateur.

    try:  # Le lancement peut échouer (fichier corrompu, droits insuffisants).
        lancer(executable)  # Démarre Docker Desktop comme un double-clic.
    except OSError as erreur:  # Erreur système au lancement.
        return f"Erreur : impossible de lancer Docker Desktop : {erreur}"  # Message d'erreur détaillé.

    return "OK : Docker Desktop est en cours de démarrage."  # Confirmation immédiate (le démarrage est asynchrone).


@mcp.tool(  # Décorateur : expose la fonction suivante comme outil MCP.
    name="ouvrir_variables_environnement",  # Nom exact de l'outil côté OpenCode.
    description="Ouvre directement la fenêtre des variables d'environnement de Windows.",  # Description lue par le modèle.
)  # Fin de la configuration du décorateur.
def ouvrir_variables_environnement() -> str:  # Outil n°3 : ouvre la boîte de dialogue des variables d'environnement.
    """Ouvre la boîte de dialogue Variables d'environnement de Windows."""  # Docstring interne de la fonction.
    system32 = dossier_systeme()  # Récupère le dossier System32 de façon robuste.
    rundll32 = system32 / "rundll32.exe"  # Binaire Windows qui charge des fonctions de panneaux de configuration.
    sysdm = system32 / "sysdm.cpl"  # Panneau "Propriétés système" contenant la fonction visée.

    if rundll32.is_file() and sysdm.is_file():  # Vérifie que les deux binaires existent avant de lancer.
        try:  # Le lancement peut échouer même si les fichiers existent (politique, antivirus).
            subprocess.Popen(  # Démarre rundll32 sans attendre sa fin (fenêtre indépendante).
                [str(rundll32), str(sysdm) + ",EditEnvironmentVariables"],  # Commande : sysdm.cpl,EditEnvironmentVariables.
                close_fds=True,  # N'hérite pas des descripteurs du serveur MCP (propreté des processus).
            )  # Fin du lancement.
            return "OK : la fenêtre des variables d'environnement est ouverte."  # Succès : la fenêtre s'affiche directement.
        except OSError as erreur:  # Échec du lancement : on tentera le repli ci-dessous.
            print(f"[variables] rundll32 : {erreur}", file=sys.stderr)  # Trace l'erreur sans casser le protocole.

    # Repli : on ouvre au moins les propriétés système avancées.
    avance = system32 / "SystemPropertiesAdvanced.exe"  # Exécutable de l'onglet "Paramètres système avancés".
    if avance.is_file():  # Vérifie la présence du repli avant de l'utiliser.
        try:  # Le repli peut lui aussi échouer.
            lancer(avance)  # Ouvre les propriétés système avancées.
        except OSError as erreur:  # Erreur système lors de l'ouverture du repli.
            return f"Erreur : impossible d'ouvrir les propriétés système : {erreur}"  # Message d'erreur détaillé.
        return (  # Confirmation en deux lignes pour rester lisible.
            "OK : les propriétés système avancées sont ouvertes. "  # Première partie du message.
            "Cliquez sur 'Variables d'environnement'."  # Indique le clic restant à faire.
        )  # Fin du message de repli.

    return "Erreur : impossible d'ouvrir les variables d'environnement sur ce système."  # Aucun moyen disponible.


if __name__ == "__main__":  # N'exécute le serveur que si le fichier est lancé directement (pas à l'import).
    mcp.run(transport="stdio")  # Démarre le serveur MCP en stdio : OpenCode communique via stdin/stdout.
