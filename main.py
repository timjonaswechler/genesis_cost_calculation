import configparser
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# ----------------------------------------------------------------------------
# TEIL 1: ERWEITERTE KLASSENSTRUKTUR
# ----------------------------------------------------------------------------

class AnlagenKomponente:
    """Basis-Klasse, berechnet Investitionskosten."""
    def __init__(self, config_allgemein):
        self.name = config_allgemein.get('name')
        self.lebensdauer = config_allgemein.getint('lebensdauer_jahre')
        self.spez_invest_eur_kw = config_allgemein.getfloat('spezifische_investitionskosten_eur_pro_kw', fallback=0) \
                                   or config_allgemein.getfloat('spezifische_investitionskosten_eur_pro_kwp', fallback=0)
        self.investitionskosten = 0.0

    def get_abschreibung_pa(self) -> float:
        return self.investitionskosten / self.lebensdauer if self.lebensdauer > 0 else 0

class Elektrolyseur(AnlagenKomponente):
    """Klasse für Elektrolyseure."""
    def __init__(self, config_allgemein, config_verbrauch, config_produktion):
        super().__init__(config_allgemein)
        self.nennleistung_kw = config_verbrauch.getfloat('nennleistung_kw')
        self.strombedarf_kwh_pa = config_verbrauch.getfloat('strombedarf_kwh_pa')
        self.h2_produktionsrate_kg_h = config_produktion.getfloat('h2_produktionsrate_kg_h')
        self.investitionskosten = self.spez_invest_eur_kw * self.nennleistung_kw

    def get_wartung_pa(self) -> float:
        return self.investitionskosten * 0.015

class EnergieErzeuger(AnlagenKomponente):
    """Übergeordnete Klasse für alle Energieerzeuger."""
    def __init__(self, config_allgemein, config_produktion, lastprofile_pfad):
        super().__init__(config_allgemein)
        profil_id = config_produktion.get('profil_id')
        try:
            profil_datei = lastprofile_pfad / f"{profil_id}.csv"
            # Lese die Prozentwerte und stelle sicher, dass sie 100% ergeben
            self.monatsprofil = pd.read_csv(profil_datei)['Prozent'] / 100
        except FileNotFoundError:
            print(f"FEHLER: Profildatei '{profil_datei}' nicht gefunden! Verwende gleichmäßige Verteilung.")
            self.monatsprofil = pd.Series([1/12] * 12)

    def get_monatliche_produktion_kwh(self) -> pd.Series:
        raise NotImplementedError("Diese Methode muss in der Unterklasse implementiert werden.")

class Windkraftanlage(EnergieErzeuger):
    """Spezifische Implementierung für Windkraft."""
    def __init__(self, config_allgemein, config_produktion, lastprofile_pfad):
        super().__init__(config_allgemein, config_produktion, lastprofile_pfad)
        self.nennleistung_kw = config_produktion.getfloat('nennleistung_kw')
        self.vollaststunden_pa = config_produktion.getfloat('vollaststunden_pa')
        self.investitionskosten = self.spez_invest_eur_kw * self.nennleistung_kw
    
    def get_monatliche_produktion_kwh(self) -> pd.Series:
        jahresproduktion = self.nennleistung_kw * self.vollaststunden_pa
        return jahresproduktion * self.monatsprofil

    def get_wartung_pa(self) -> float:
        return self.investitionskosten * 0.02

class PVAnlage(EnergieErzeuger):
    """Spezifische Implementierung für PV."""
    def __init__(self, config_allgemein, config_produktion, lastprofile_pfad):
        super().__init__(config_allgemein, config_produktion, lastprofile_pfad)
        self.nennleistung_kwp = config_produktion.getfloat('nennleistung_kwp')
        self.sonneneinstrahlung_kwh_kwp = config_produktion.getfloat('sonneneinstrahlung_kwh_kwp')
        self.investitionskosten = self.spez_invest_eur_kw * self.nennleistung_kwp

    def get_monatliche_produktion_kwh(self) -> pd.Series:
        jahresproduktion = self.nennleistung_kwp * self.sonneneinstrahlung_kwh_kwp
        return jahresproduktion * self.monatsprofil

    def get_wartung_pa(self) -> float:
        return self.investitionskosten * 0.015

# ----------------------------------------------------------------------------
# TEIL 2: DAS HAUPTPROJEKT MIT MONATLICHER ANALYSE
# ----------------------------------------------------------------------------

class WasserstoffProjekt:
    def __init__(self, anlagen_pfad: Path, lastprofile_pfad: Path):
        self.anlagen_pfad = anlagen_pfad
        self.lastprofile_pfad = lastprofile_pfad
        self.alle_komponenten = []
        self._parse_projekt_struktur()

    def _parse_projekt_struktur(self):
        # ... (Parser bleibt fast gleich, ruft aber neue Klassen auf)
        print("--- Lese Projektstruktur ---")
        config = configparser.ConfigParser()
        for typ_ordner in self.anlagen_pfad.iterdir():
            if not typ_ordner.is_dir(): continue
            
            typ = typ_ordner.name
            for ini_file in typ_ordner.glob('*.ini'):
                try:
                    config.read(ini_file)
                    allgemein = config['Allgemein']
                    produktion = config['Produktion']
                    
                    if typ == 'elektrolyseure':
                        komponente = Elektrolyseur(allgemein, config['Verbrauch'], produktion)
                    elif typ == 'windkraft':
                        komponente = Windkraftanlage(allgemein, produktion, self.lastprofile_pfad)
                    elif typ == 'pv':
                        komponente = PVAnlage(allgemein, produktion, self.lastprofile_pfad)
                    else:
                        continue
                        
                    self.alle_komponenten.append(komponente)
                    print(f"  -> '{komponente.name}' geladen.")
                except Exception as e:
                    print(f"  -> FEHLER bei {ini_file.name}: {e}")

    def starte_monatliche_analyse(self):
        elektrolyseure = [k for k in self.alle_komponenten if isinstance(k, Elektrolyseur)]
        erzeuger = [k for k in self.alle_komponenten if isinstance(k, EnergieErzeuger)]

        if not elektrolyseure:
            print("FEHLER: Kein Elektrolyseur für Analyse gefunden.")
            return
        
        # 1. Berechne monatliche Erzeugung und Verbrauch
        monatliche_erzeugung = sum(k.get_monatliche_produktion_kwh() for k in erzeuger)
        monatlicher_bedarf = elektrolyseure[0].strombedarf_kwh_pa / 12

        # 2. Erstelle ein DataFrame für die Analyse
        df = pd.DataFrame({
            'Erzeugung': monatliche_erzeugung,
            'Bedarf_Elektrolyseur': monatlicher_bedarf
        })
        df.index = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']

        df['Selbstversorgung'] = df[['Erzeugung', 'Bedarf_Elektrolyseur']].min(axis=1)
        df['Netzeinspeisung_Ueberschuss'] = (df['Erzeugung'] - df['Bedarf_Elektrolyseur']).clip(lower=0)
        df['Netzbezug_Defizit'] = (df['Bedarf_Elektrolyseur'] - df['Erzeugung']).clip(lower=0)

        # 3. Berechne Jahresergebnisse und Kosten
        jahres_erzeugung = df['Erzeugung'].sum()
        jahres_selbstversorgung = df['Selbstversorgung'].sum()
        
        h2_produktionsstunden = jahres_selbstversorgung / elektrolyseure[0].nennleistung_kw
        h2_produktion_kg_pa = h2_produktionsstunden * elektrolyseure[0].h2_produktionsrate_kg_h
        
        gesamte_investition = sum(k.investitionskosten for k in self.alle_komponenten)
        kosten = {
            'Abschreibung': sum(k.get_abschreibung_pa() for k in self.alle_komponenten),
            'Wartung': sum(k.get_wartung_pa() for k in self.alle_komponenten),
            'Zinsen (Annahme)': gesamte_investition * 0.5 * 0.07,
            # Hier könnten Kosten für Netzbezug etc. hinzukommen
        }
        selbstkosten_total_pa = sum(kosten.values())
        gestehungskosten_pro_kg_h2 = selbstkosten_total_pa / h2_produktion_kg_pa if h2_produktion_kg_pa > 0 else float('inf')

        # 4. Ausgabe und Visualisierung
        print("\n--- Monatliche Energiebilanz (in kWh) ---")
        print(df.round(0))
        
        print("\n--- Jährliche Zusammenfassung ---")
        print(f"Gesamtinvestition: {gesamte_investition:,.0f} €")
        print(f"Gesamte Stromerzeugung: {jahres_erzeugung:,.0f} kWh")
        print(f"Davon für Elektrolyse genutzt: {jahres_selbstversorgung:,.0f} kWh ({jahres_selbstversorgung/jahres_erzeugung*100:.1f}%)")
        print(f"Produzierter Wasserstoff: {h2_produktion_kg_pa:,.0f} kg")
        print(f"\nGESAMTE GESTEHUNGSKOSTEN: {gestehungskosten_pro_kg_h2:.2f} €/kg H2")

        self._visualisiere_bilanz(df)

    def _visualisiere_bilanz(self, df: pd.DataFrame):
        """Erstellt ein gestapeltes Balkendiagramm der monatlichen Energiebilanz."""
        fig, ax = plt.subplots(figsize=(12, 7))

        # Gestapelte Balken für Erzeugung
        ax.bar(df.index, df['Selbstversorgung'], label='Selbstversorgung Elektrolyseur', color='green')
        ax.bar(df.index, df['Netzeinspeisung_Ueberschuss'], bottom=df['Selbstversorgung'], label='Überschuss (Netzeinspeisung)', color='yellowgreen')

        # Linie für den Bedarf
        ax.plot(df.index, df['Bedarf_Elektrolyseur'], color='red', marker='o', linestyle='--', label='Bedarf Elektrolyseur')

        ax.set_ylabel('Energie (kWh)')
        ax.set_title('Monatliche Energiebilanz: Erzeugung vs. Verbrauch')
        ax.legend()
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()
        plt.show()

# ----------------------------------------------------------------------------
# TEIL 3: AUSFÜHRUNG
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    PROJEKT_BASIS_PFAD = Path(__file__).parent
    ANLAGEN_PFAD = PROJEKT_BASIS_PFAD / 'anlage'
    LASTPROFILE_PFAD = PROJEKT_BASIS_PFAD / 'lastprofile'
    
    projekt = WasserstoffProjekt(anlagen_pfad=ANLAGEN_PFAD, lastprofile_pfad=LASTPROFILE_PFAD)
    projekt.starte_monatliche_analyse()