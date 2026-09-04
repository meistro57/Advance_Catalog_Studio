# utils/schema_templates.py
"""DDL and starter seed data for the two catalog schemas we reverse-engineered
tonight: the Anchors* shape (HY-200, KB3TZ) and the Bolts* shape (A325).

Column names/types match what we observed in real exports. PRIMARY KEY /
IDENTITY choices are our own reasonable defaults for a *freshly created*
catalog -- the original AS-generated exports may not have had these
constraints. Test-import a fresh catalog before trusting it for real work.
"""

ANCHOR_TABLES = [
    """
    CREATE TABLE AnchorsDefinition (
        ID INT IDENTITY(1,1) PRIMARY KEY,
        AnchorID INT NULL,
        Length FLOAT NULL,
        ThreadLength FLOAT NULL,
        TopDistance FLOAT NULL,
        DistanceF FLOAT NULL,
        DistanceE FLOAT NULL,
        DistanceA FLOAT NULL,
        DistanceO FLOAT NULL,
        DistanceC FLOAT NULL,
        BottomDistance FLOAT NULL,
        HeadHeight FLOAT NULL,
        HeadDiameter FLOAT NULL,
        NumberOfHeadEdges INT NULL,
        HookRadius FLOAT NULL,
        PartName NVARCHAR(64) NULL,
        Weight FLOAT NULL,
        OwnerText NVARCHAR(15) NULL
    );
    """,
    """
    CREATE TABLE AnchorsHoleDefinition (
        ID INT IDENTITY(1,1) PRIMARY KEY,
        AnchorNameID INT NOT NULL,
        Location INT NULL,
        HoleType INT NULL,
        HoleTolerance FLOAT NULL,
        Depth FLOAT NULL,
        Angle INT NULL,
        HeadDiameter FLOAT NULL
    );
    """,
    """
    CREATE TABLE AnchorsName (
        ID INT IDENTITY(1,1) PRIMARY KEY,
        Standard NVARCHAR(64) NULL,
        ClassID INT NULL,
        MaterialKey NVARCHAR(64) NULL,
        Explodable BIT NOT NULL DEFAULT 1,
        Source NVARCHAR(15) NULL,
        Diameter FLOAT NULL,
        SetName NVARCHAR(64) NULL,
        OwnerText NVARCHAR(15) NULL,
        NumItems INT NULL,
        DIN1 NVARCHAR(32) NULL, Diameter1 FLOAT NULL, Material1 NVARCHAR(16) NULL, Position1 INT NULL,
        DIN2 NVARCHAR(32) NULL, Diameter2 FLOAT NULL, Material2 NVARCHAR(16) NULL, Position2 INT NULL,
        DIN3 NVARCHAR(32) NULL, Diameter3 FLOAT NULL, Material3 NVARCHAR(16) NULL, Position3 INT NULL,
        DIN4 NVARCHAR(32) NULL, Diameter4 FLOAT NULL, Material4 NVARCHAR(16) NULL, Position4 INT NULL,
        DIN5 NVARCHAR(32) NULL, Diameter5 FLOAT NULL, Material5 NVARCHAR(16) NULL, Position5 INT NULL,
        DIN6 NVARCHAR(32) NULL, Diameter6 FLOAT NULL, Material6 NVARCHAR(16) NULL, Position6 INT NULL
    );
    """,
    """
    CREATE TABLE AnchorsStandard (
        [Key] NVARCHAR(64) NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        OwnerText NVARCHAR(15) NULL
    );
    """,
    """
    CREATE TABLE BoltsDiameters (
        [Key] FLOAT NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        Description NVARCHAR(64) NULL
    );
    """,
    """
    CREATE TABLE BoltsDistances (
        Diameter FLOAT NOT NULL,
        HoleTolerance FLOAT NOT NULL,
        along FLOAT NULL,
        across FLOAT NULL,
        Description NVARCHAR(64) NULL
    );
    """,
    """
    CREATE TABLE SetNutsBolts (
        Standard NVARCHAR(32) NOT NULL,
        Material NVARCHAR(64) NOT NULL,
        Diameter FLOAT NOT NULL,
        Height FLOAT NULL,
        NumberOfCorners INT NULL,
        OutsideDiameter FLOAT NULL,
        Name NVARCHAR(255) NULL,
        Weight FLOAT NULL,
        ItemNumber NVARCHAR(16) NULL,
        OwnerText NVARCHAR(15) NULL,
        Source NVARCHAR(15) NULL,
        Type INT NULL
    );
    """,
    """
    CREATE TABLE Sets (
        [Key] NVARCHAR(64) NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        OwnerText NVARCHAR(15) NULL
    );
    """,
    """
    CREATE TABLE Sources (
        Short NVARCHAR(15) NOT NULL PRIMARY KEY,
        Long NVARCHAR(255) NULL
    );
    """,
    """
    CREATE TABLE StrengthClass (
        [Key] NVARCHAR(64) NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        OwnerText NVARCHAR(15) NULL
    );
    """,
]

ANCHOR_SEED = [
    "INSERT INTO Sources (Short, Long) VALUES ('ASTM A563', 'ASTM A563');",
    "INSERT INTO Sources (Short, Long) VALUES ('ASTM F436', 'ASTM F436');",
    "INSERT INTO Sources (Short, Long) VALUES ('Hilti Anker', 'Hilti Katalog: D\u00fcbeltechnik');",
    "INSERT INTO StrengthClass ([Key], RunName, OwnerText) VALUES ('5.8', '5.8', 'DSC');",
    "INSERT INTO StrengthClass ([Key], RunName, OwnerText) VALUES ('10.9', '10.9', 'DSC');",
    "INSERT INTO StrengthClass ([Key], RunName, OwnerText) VALUES ('Carbon Steel', 'Carbon Steel', 'DSC');",
    "INSERT INTO Sets ([Key], RunName, OwnerText) VALUES ('MuS', 'NaW', 'DSC');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (8.0, '  8.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (9.525, ' 3/8 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (10.0, ' 10.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (12.0, ' 12.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (12.7, ' 1/2 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (15.875, ' 5/8 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (16.0, ' 16.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (19.05, ' 3/4 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (20.0, ' 20.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (22.225, ' 7/8 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (24.0, ' 24.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (25.4, ' 1 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (27.0, ' 27.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (30.0, ' 30.00 mm');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (31.75, ' 1 1/4 inch');",
]

BOLT_TABLES = [
    """
    CREATE TABLE BoltsDiameters (
        [Key] FLOAT NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        Description NVARCHAR(64) NULL
    );
    """,
    """
    CREATE TABLE BoltsDistances (
        Diameter FLOAT NOT NULL,
        HoleTolerance FLOAT NOT NULL,
        along FLOAT NULL,
        across FLOAT NULL,
        Description NVARCHAR(64) NULL
    );
    """,
    """
    CREATE TABLE ScrewNew (
        Standard NVARCHAR(32) NOT NULL,
        [Set] NVARCHAR(32) NOT NULL,
        Material NVARCHAR(16) NOT NULL,
        Diameter FLOAT NOT NULL,
        OwnerText NVARCHAR(15) NULL,
        Source NVARCHAR(15) NULL,
        NumberOfItems INT NULL,
        Location INT NULL,
        HoleType INT NULL,
        HoleTolerance FLOAT NULL,
        Depth FLOAT NULL,
        Angle INT NULL,
        HeadDiameter FLOAT NULL,
        GripLengthMin1 FLOAT NULL, GripLengthMax1 FLOAT NULL, ScrewLengthBase1 FLOAT NULL, ScrewLengthDelta1 FLOAT NULL,
        GripLengthMin2 FLOAT NULL, GripLengthMax2 FLOAT NULL, ScrewLengthBase2 FLOAT NULL, ScrewLengthDelta2 FLOAT NULL,
        GripLengthMin3 FLOAT NULL, GripLengthMax3 FLOAT NULL, ScrewLengthBase3 FLOAT NULL, ScrewLengthDelta3 FLOAT NULL,
        GripLengthMin4 FLOAT NULL, GripLengthMax4 FLOAT NULL, ScrewLengthBase4 FLOAT NULL, ScrewLengthDelta4 FLOAT NULL,
        GripLengthMin5 FLOAT NULL, GripLengthMax5 FLOAT NULL, ScrewLengthBase5 FLOAT NULL, ScrewLengthDelta5 FLOAT NULL,
        GripLengthMin6 FLOAT NULL, GripLengthMax6 FLOAT NULL, ScrewLengthBase6 FLOAT NULL, ScrewLengthDelta6 FLOAT NULL,
        GripLengthMin7 FLOAT NULL, GripLengthMax7 FLOAT NULL, ScrewLengthBase7 FLOAT NULL, ScrewLengthDelta7 FLOAT NULL
    );
    """,
    """
    CREATE TABLE SetBolts (
        ID INT IDENTITY(1,1) PRIMARY KEY,
        Standard NVARCHAR(32) NOT NULL,
        Material NVARCHAR(64) NOT NULL,
        Diameter FLOAT NOT NULL,
        Length FLOAT NOT NULL,
        ScrewHeadOuterDiameter FLOAT NULL,
        HeadHeight FLOAT NULL,
        NumberOfCorners INT NULL,
        Name NVARCHAR(255) NULL,
        Weight FLOAT NULL,
        OwnerText NVARCHAR(15) NULL,
        Source NVARCHAR(15) NULL,
        Type INT NULL
    );
    """,
    """
    CREATE TABLE SetNutsBolts (
        Standard NVARCHAR(32) NOT NULL,
        Material NVARCHAR(64) NOT NULL,
        Diameter FLOAT NOT NULL,
        Height FLOAT NULL,
        NumberOfCorners INT NULL,
        OutsideDiameter FLOAT NULL,
        Name NVARCHAR(255) NULL,
        Weight FLOAT NULL,
        ItemNumber NVARCHAR(16) NULL,
        OwnerText NVARCHAR(15) NULL,
        Source NVARCHAR(15) NULL,
        Type INT NULL
    );
    """,
    """
    CREATE TABLE SetOfBolts (
        Standard NVARCHAR(32) NOT NULL,
        [Set] NVARCHAR(32) NOT NULL,
        Material NVARCHAR(64) NOT NULL,
        Diameter FLOAT NOT NULL,
        BindingLength FLOAT NULL,
        Explodeable BIT NOT NULL DEFAULT 1,
        OwnerText NVARCHAR(15) NULL,
        Source NVARCHAR(15) NULL,
        Length INT NULL,
        DIN1 NVARCHAR(32) NULL, [Diameter1 (mm)] FLOAT NULL, Material1 NVARCHAR(16) NULL, Position1 INT NULL,
        DIN2 NVARCHAR(32) NULL, [Diameter2 (mm)] FLOAT NULL, Material2 NVARCHAR(16) NULL, Position2 INT NULL,
        DIN3 NVARCHAR(32) NULL, [Diameter3 (mm)] FLOAT NULL, Material3 NVARCHAR(16) NULL, Position3 INT NULL,
        DIN4 NVARCHAR(32) NULL, [Diameter4 (mm)] FLOAT NULL, Material4 NVARCHAR(16) NULL, Position4 INT NULL,
        DIN5 NVARCHAR(32) NULL, [Diameter5 (mm)] FLOAT NULL, Material5 NVARCHAR(16) NULL, Position5 INT NULL,
        DIN6 NVARCHAR(32) NULL, [Diameter6 (mm)] FLOAT NULL, Material6 NVARCHAR(16) NULL, Position6 INT NULL
    );
    """,
    """
    CREATE TABLE Sets (
        [Key] NVARCHAR(64) NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        OwnerText NVARCHAR(15) NULL
    );
    """,
    """
    CREATE TABLE Sources (
        Short NVARCHAR(15) NOT NULL PRIMARY KEY,
        Long NVARCHAR(255) NULL
    );
    """,
    """
    CREATE TABLE Standard (
        [Key] NVARCHAR(64) NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        AutoLengthCalc BIT NOT NULL DEFAULT 0,
        StandardSet NVARCHAR(64) NULL,
        OwnerText NVARCHAR(15) NULL
    );
    """,
    """
    CREATE TABLE StrengthClass (
        [Key] NVARCHAR(64) NOT NULL PRIMARY KEY,
        RunName NVARCHAR(64) NULL,
        OwnerText NVARCHAR(15) NULL
    );
    """,
]

BOLT_SEED = [
    "INSERT INTO Sources (Short, Long) VALUES ('ASTM A325', 'ASTM A325');",
    "INSERT INTO Sources (Short, Long) VALUES ('ASTM A563', 'ASTM A563');",
    "INSERT INTO Sources (Short, Long) VALUES ('ASTM F436', 'ASTM F436');",
    "INSERT INTO StrengthClass ([Key], RunName, OwnerText) VALUES ('10.9', '10.9', 'DSC');",
    "INSERT INTO Sets ([Key], RunName, OwnerText) VALUES ('M', 'N', 'DSC');",
    "INSERT INTO Sets ([Key], RunName, OwnerText) VALUES ('MuS', 'NaW', 'DSC');",
    "INSERT INTO Sets ([Key], RunName, OwnerText) VALUES ('Mu2S', 'Na2W', 'DSC');",
    "INSERT INTO Sets ([Key], RunName, OwnerText) VALUES ('MuKS', 'NaWW', 'DSC');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (12.7, ' 1/2 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (15.875, ' 5/8 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (19.05, ' 3/4 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (22.225, ' 7/8 inch');",
    "INSERT INTO BoltsDiameters ([Key], RunName) VALUES (25.4, ' 1 inch');",
]

CATALOG_TEMPLATES = {
    "anchor": {"label": "Anchor Catalog", "tables": ANCHOR_TABLES, "seed": ANCHOR_SEED},
    "bolt": {"label": "Bolt Catalog", "tables": BOLT_TABLES, "seed": BOLT_SEED},
}
