# Flash Trombi

Application Windows d'apprentissage des noms d'élèves à partir d'un trombinoscope PDF.

## Pour un utilisateur normal

Télécharger **FlashTrombi-Setup.exe** depuis la page Releases, l'installer, puis lancer **Flash Trombi** depuis le Bureau ou le menu Démarrer.

Aucun Python, Git ou terminal n'est nécessaire.

### Premier lancement

1. cliquer sur **Ajouter une classe** ;
2. donner un nom à la classe ;
3. choisir le PDF du trombinoscope ;
4. vérifier les portraits détectés et décocher les mauvaises vignettes ;
5. créer la classe ;
6. cliquer sur **Continuer** pour commencer l'entraînement.

## Entraînement

- séries de 10 élèves maximum ;
- priorité : `Mémorisé → Vu → Non commencé` ;
- les 5 derniers élèves demandés sont évités quand le groupe le permet ;
- 3 bonnes réponses dans une série = mémorisé pour la date du jour ;
- lors d'un jour suivant, un élève mémorisé est révisé en priorité ;
- une réussite ajoute la nouvelle date ;
- un échec remet l'élève en `Vu` et ouvre un nouveau cycle ;
- 3 jours mémorisés dans le même cycle = `Acquis` ;
- les acquis reviennent en entretien lorsque toute la classe est acquise ;
- en entretien, un acquis oublié repasse en `Vu` et recommence un cycle.

Le flux d'une carte est : **photo → afficher le nom → “Tu l'avais ?” → Oui / Non → carte suivante automatiquement**.

## Données et confidentialité

Sous Windows, les données sont stockées dans :

```text
%LOCALAPPDATA%\FlashTrombi\
```

On y trouve la base SQLite, les PDF et les portraits. Une mise à jour ou une réinstallation du programme n'efface pas ce dossier.

L'application permet de télécharger une sauvegarde ZIP et de la restaurer. Ne jamais ajouter de vrais trombinoscopes ou données d'élèves au dépôt GitHub.

## Développement

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate
# macOS/Linux : source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Pour isoler les données de test :

```powershell
$env:FLASH_TROMBI_DATA_DIR="$PWD\data-test"
python -m streamlit run app.py
```

## Construire l'installateur Windows

Pré-requis développeur : Python et Inno Setup 6.

```powershell
.\build_windows.ps1
```

Le résultat est `installer-output\FlashTrombi-Setup.exe`.

GitHub Actions peut également construire automatiquement l'installateur. Un tag comme `v0.3.0` crée un build Windows et attache l'installateur à la Release GitHub correspondante.
