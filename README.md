# Flash Trombi

Application Streamlit locale pour apprendre progressivement les noms d'une classe à partir d'un trombinoscope PDF.

## Principe

- 1 PDF importé = 1 classe nommée.
- Les données sont stockées localement dans `data/` avec SQLite.
- Les portraits et les petites étiquettes de nom sont extraits du PDF.
- Une session travaille jusqu'à 10 élèves.
- Priorité : **Mémorisé → Vu → Non commencé**.
- Les **Acquis** ne reviennent qu'en entretien lorsque toute la classe est acquise.
- Les 5 derniers élèves demandés sont évités lorsque le groupe est assez grand.

## Cycle d'un élève

1. `Non commencé` → devient `Vu` lorsqu'il entre dans un groupe de travail.
2. Un élève `Vu` doit être reconnu 3 fois dans la session pour devenir `Mémorisé [date]`.
3. Un jour suivant, un élève `Mémorisé` est revu en priorité :
   - bonne réponse → la nouvelle date est ajoutée ;
   - mauvaise réponse → retour à `Vu` et démarrage d'un nouveau cycle.
4. Après 3 dates différentes dans le même cycle → `Acquis`.

Les anciens cycles restent dans SQLite pour conserver l'historique, mais ils ne comptent plus après une remise à zéro.

## Installation Windows

```powershell
git clone https://github.com/JulSez/flash-trombi.git
cd flash-trombi
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Données locales

L'application crée automatiquement :

```text
data/
├── flash_trombi.sqlite3
└── classes/
    └── 0001-Ma-classe/
        ├── source.pdf
        ├── portraits/
        └── labels/
```

Le dossier `data/` est ignoré par Git afin d'éviter d'envoyer des trombinoscopes ou des données d'élèves sur GitHub.
