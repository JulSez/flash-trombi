# Flash Trombinoscope

Petite application Streamlit qui :

1. charge un trombinoscope PDF local ;
2. extrait les portraits intégrés et associe le texte proche comme nom/prénom ;
3. tente de détecter la classe ;
4. permet de corriger les données dans un tableau éditable ;
5. tire au hasard un élève d'une classe ;
6. affiche sa photo, puis révèle son nom à la demande.

## Installation

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\\Scripts\\Activate.ps1

pip install -r requirements.txt
streamlit run app.py
```

## Limites

- Fonctionne surtout avec des PDF contenant de vraies images et du texte sélectionnable.
- Un PDF scanné nécessite un module OCR supplémentaire.
- La détection nom/prénom et classe est heuristique : utiliser la table de correction avant les flash cards.
- Utiliser uniquement des documents que vous êtes autorisé à traiter, en particulier s'ils contiennent des données d'élèves mineurs.

## Confidentialité

Le dépôt ne doit pas contenir de trombinoscopes réels, de photos d’élèves ni d’exports CSV nominatifs.
Le fichier `.gitignore` fourni exclut ces données par défaut.
