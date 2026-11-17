
from enum import StrEnum


class Forme(StrEnum):
    COMPRIME = "Comprimé"
    GELULE = "Gélule"
    POUDRE = "Poudre"
    SIROP = "Sirop"
    SOLUTION_BUVABLE = "Solution buvable"
    SUSPENSION = "Suspension"
    POMMADE = "Pommade"
    CREME = "Crème"
    GEL = "Gel"
    SUPPOSITOIRE = "Suppositoire"
    AMPOULE = "Ampoule"
    COLLYRE = "Collyre"
    GOUTTES = "Gouttes"
    INJECTABLE = "Injectable"
    SPRAY = "Spray"
    PATCH = "Patch"
    OVULE = "Ovule"
    AUTRE = "Autre"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)


class UniteVente(StrEnum):
    BOITE = "Boîte"
    FLACON = "Flacon"
    TUBE = "Tube"
    SACHET = "Sachet"
    AMPOULE = "Ampoule"
    PLAQUETTE = "Plaquette"
    COMPRIME = "Comprimé"
    GELULE = "Gélule"
    UNITE = "Unité"
    BIDON = "Bidon"
    POT = "Pot"
    SPRAY = "Spray"
    AUTRE = "Autre"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)

class SousUnite(StrEnum):
    COMPRIME = "Comprimé"
    GELULE = "Gélule"
    SACHET = "Sachet"
    AMPOULE = "Ampoule"
    PLAQUETTE = "Plaquette"
    OVULE = "Ovule"
    SUPPOSITOIRE = "Suppositoire"
    DOSE = "Dose"
    GOUTTE = "Goutte"
    BOUFFEE = "Bouffée"
    PATCH = "Patch"
    APPLICATION = "Application"
    ML = "ml"
    CL = "cl"
    L = "L"
    G = "g"
    MG = "mg"
    KG = "kg"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)

