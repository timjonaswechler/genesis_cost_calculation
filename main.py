import configparser
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# ----------------------------------------------------------------------------
# TEIL 0: Settings
# ----------------------------------------------------------------------------
Wartungskosten_in_prozent = {
    'elektrolyseur': 0.015,  # 1.5% der Investition
    'windkraft': 0.020,      # 2% der Investition
    'pv': 0.020              # 2% der Investition
}
Installationskosten_in_prozent = {
    'elektrolyseur': 0.05,   # 5% der Investition
    'windkraft': 0.05,        # 5% der Investition
    'pv': 0.05                # 5% der Investition
}
auslastung_elektrolyseur = 0.97  # 97% Auslastung für Elektrolyseure
# ----------------------------------------------------------------------------
# TEIL 1: ANGEPASSTE KLASSEN FÜR IHRE NEUEN DATEN
# ----------------------------------------------------------------------------

class AnlagenKomponente:
    """Basis-Klasse. Berechnet jetzt die Investitionskosten dynamisch."""
    def __init__(self, config_allgemein: configparser.SectionProxy):
        self.name = config_allgemein.get('name')
        self.lebensdauer = config_allgemein.getint('lebensdauer_jahre')
        self.spezifische_invest_eur_pro_kw = config_allgemein.getfloat('spezifische_investitionskosten')
        self.nennleistung_kw = config_allgemein.getfloat('nennleistung', fallback=0.0)

    def get_abschreibung_pa(self) -> float:
        return self.investitionskosten / self.lebensdauer if self.lebensdauer > 0 else 0

class Elektrolyseur(AnlagenKomponente):
    """Liest die Elektrolyseur-spezifischen INI-Dateien."""
    def __init__(self, config_allgemein, config_verbrauch, config_produktion):
        super().__init__(config_allgemein)
        # Verbrauch
        self.wasser = config_verbrauch.getfloat('wasser')
        # Produktion
        self.h2_produktionsrate_kg_h = config_produktion.getfloat('h2_produktionsrate_kg_h')

        # Berechne die Gesamtinvestition basierend auf der Nennleistung
        self.investitionskosten = self.spezifische_invest_eur_pro_kw * self.nennleistung_kw
        
    def get_wartung_pa(self) -> float:
        # Annahme: 1.5% der Investition als jährliche Wartungskosten
        return self.investitionskosten * Wartungskosten_in_prozent['elektrolyseur']

class EnergieErzeuger(AnlagenKomponente):
    """Liest Wind/PV-spezifische INI-Dateien."""
    def __init__(self, config_allgemein, config_produktion):
        super().__init__(config_allgemein)
        # Produktion
        self.nennleistung_mw = config_produktion.getfloat('nennleistung_MW')
        self.vollaststunden_pa = config_produktion.getfloat('vollaststunden')
        
        # Berechne die Gesamtinvestition (Einheit von MW auf kW umrechnen)
        self.investitionskosten = self.spezifische_invest_eur_pro_kw * (self.nennleistung_mw * 1000)

    def get_erzeugte_energie_kwh_pa(self) -> float:
        """Berechnet die jährliche Energieerzeugung."""
        return self.nennleistung_mw * 1000 * self.vollaststunden_pa
        
    def get_wartung_pa(self) -> float:
        # Annahme: 2% der Investition als jährliche Wartungskosten
        return self.investitionskosten * Wartungskosten_in_prozent['windkraft']

# ----------------------------------------------------------------------------
# TEIL 2: ANGEPASSTER PARSER UND ANALYSE-LOGIK
# ----------------------------------------------------------------------------

class WasserstoffProjekt:
    """Liest die neue Projektstruktur und führt die Analyse durch."""
    def __init__(self, anlagen_pfad: Path):
        self.anlagen_pfad = anlagen_pfad
        self.alle_komponenten = []
        
        # Feste Projekt-Parameter
        self.fremdkapital_zins = 0.07
        self.lohnkosten_pa = 250_000 # Beispielwert
        
        self._parse_projekt_struktur()

    def _parse_projekt_struktur(self):
        print("--- Lese Projektstruktur ---")
        config = configparser.ConfigParser()

        for typ_ordner in self.anlagen_pfad.iterdir():
            if not typ_ordner.is_dir(): continue
            
            komponenten_typ = typ_ordner.name
            print(f"Analysiere Typ: '{komponenten_typ}'")

            for ini_file in typ_ordner.glob('*.ini'):
                try:
                    config.read(ini_file)
                    allgemein = config['Allgemein']
                    
                    if komponenten_typ == 'elektrolyseure':
                        komponente = Elektrolyseur(allgemein, config['Verbrauch'], config['Produktion'])
                    elif komponenten_typ in ['windkraft', 'pv']:
                        komponente = EnergieErzeuger(allgemein, config['Produktion'])
                    else:
                        continue # Unbekannten Typ überspringen
                        
                    self.alle_komponenten.append(komponente)
                    print(f"  -> Komponente '{komponente.name}' geladen. Invest: {komponente.investitionskosten:,.0f} €")
                except Exception as e:
                    print(f"  -> FEHLER beim Lesen von {ini_file.name}: {e}")
        print(f"--- {len(self.alle_komponenten)} Komponenten erfolgreich geladen ---\n")

    def starte_analyse(self):
        if not self.alle_komponenten:
            print("Analyse abgebrochen: Keine Komponenten geladen.")
            return

        elektrolyseure = [k for k in self.alle_komponenten if isinstance(k, Elektrolyseur)]
        energie_erzeuger = [k for k in self.alle_komponenten if isinstance(k, EnergieErzeuger)]

        if not elektrolyseure:
            print("Analyse abgebrochen: Kein Elektrolyseur im Projekt.")
            return
            
        # 1. Energie- und Wasserstoffproduktion
        erzeugte_energie_kwh_pa = sum(k.get_erzeugte_energie_kwh_pa() for k in energie_erzeuger)
        
        # Gesamte Nennleistung aller Elektrolyseure in kW
        elektrolyseur_leistung_kw = sum(k.nennleistung_kw for k in elektrolyseure)
        
        # Betriebsstunden des Elektrolyseurs (begrenzt durch Energie / Leistung)
        betriebsstunden_pa = erzeugte_energie_kwh_pa / elektrolyseur_leistung_kw if elektrolyseur_leistung_kw > 0 else 0
        
        # Produzierter Wasserstoff
        h2_produktion_kg_pa = sum(k.h2_produktionsrate_kg_h * betriebsstunden_pa for k in elektrolyseure)

        # 2. Kostenkalkulation
        gesamte_investition = sum(k.investitionskosten for k in self.alle_komponenten)
        
        kosten = {
            'Abschreibung': sum(k.get_abschreibung_pa() for k in self.alle_komponenten),
            'Wartung': sum(k.get_wartung_pa() for k in self.alle_komponenten),
            'Verzinsung (FK)': gesamte_investition * 0.5 * self.fremdkapital_zins, # Annahme: 50% FK
            'Löhne': self.lohnkosten_pa
        }
        
        selbstkosten_total_pa = sum(kosten.values())
        gestehungskosten_pro_kg_h2 = selbstkosten_total_pa / h2_produktion_kg_pa if h2_produktion_kg_pa > 0 else float('inf')

        # 3. Ausgabe
        print("--- Analyseergebnisse ---")
        print(f"Gesamtinvestition: {gesamte_investition:,.2f} €")
        print(f"Jährl. Energieerzeugung: {erzeugte_energie_kwh_pa:,.0f} kWh")
        print(f"Max. Betriebsstunden Elektrolyse: {betriebsstunden_pa:,.0f} h/a")
        print(f"Jährl. H2-Produktion: {h2_produktion_kg_pa:,.2f} kg")
        print("-" * 25)
        print("Jährliche Kostenaufschlüsselung:")
        for name, wert in kosten.items():
            print(f"  - {name}: {wert:,.2f} €")
        print(f"-> Gesamte Selbstkosten p.a.: {selbstkosten_total_pa:,.2f} €")
        print("-" * 25)
        print(f"WASSERSTOFFGESTEHUNGSKOSTEN: {gestehungskosten_pro_kg_h2:.2f} €/kg")

        # 4. Visualisierung
        plt.pie(kosten.values(), labels=kosten.keys(), autopct='%1.1f%%', startangle=90)
        plt.title("Verteilung der jährlichen Gesamtkosten")
        plt.show()

# ----------------------------------------------------------------------------
# TEIL 3: AUSFÜHRUNG
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    PROJEKT_BASIS_PFAD = Path(__file__).parent
    ANLAGEN_PFAD = PROJEKT_BASIS_PFAD / 'anlage' # Ordnername angepasst
    
    projekt = WasserstoffProjekt(anlagen_pfad=ANLAGEN_PFAD)
    projekt.starte_analyse()