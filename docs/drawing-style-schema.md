# DrawingStyleSample schema inventory (drawing-style scope)

Scope: tables prefixed `Detail*` and `Det*` used by drawing style authoring/browsing in Phase 1.

DetailStyle linkage: `DetailStyle.Key` is the central style identifier. Child/adjacent tables (notably `DetailStyleMapNew`, `DetailStyleMapItems`, and multiple `Det*` strategy/annotation tables) reference style/process/request definitions to assemble final drawing-style behavior.

## DetAnnotationType
- PK: Key
- Rows: 6
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, ObjectQualifier:int, OwnerText:nvarchar, Content:nvarchar

## DetArrangerControl
- PK: Key
- Rows: 0
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, UseBasePositionOnFailure:int, TerminateOnFirstFit:int, ArrangeGlobally:int, AllowOppositeAngles:int, …

## DetArrangerStrategy
- PK: Key
- Rows: 5
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, TerminateOnFirstFit:int, ArrangeGlobally:int, ArrangeInCenter:int, OwnerText:nvarchar, …

## DetBaseCategories
- PK: Key
- Rows: 1
- Purpose: Supporting lookup/configuration table used by drawing-style processing.
- Columns (sample): Key:int, Category:nvarchar, OwnerText:nvarchar, Image:nvarchar, ImageInactive:nvarchar

## DetGridReferenceSettings
- PK: Key
- Rows: 2
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, Color:int, Linetype:nvarchar, FrameType:int, OwnerText:nvarchar

## DetHatchSettings
- PK: Key
- Rows: 3
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, PatternName:nvarchar, Scale:float, Angle:float, Color:int, …

## DetManualAnnotationType
- PK: Key
- Rows: 0
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, ObjectQualifier:int, Selected:nvarchar, LeaderStyle:int, Content:nvarchar

## DetObjAnnotationGroup
- PK: Key
- Rows: 3
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, BitmapId:int, BitmapImage:nvarchar

## DetObjAnnotationStrategy
- PK: Key
- Rows: 8
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, SystemByObject:bit, TextDir1:int, TextDir2:int, AnnotationType:int, …

## DetObjAppearance
- PK: Key
- Rows: 13
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, BodyVisible:int, Axis:int, VisibleSymbols:int, HiddenSymbols:int, …

## DetObjQualifierSet
- PK: Key
- Rows: 40
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, Group:int, OwnerText:nvarchar

## DetObjQualifierSetGroup
- PK: Key
- Rows: 11
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, BitmapId:int, BitmapImage:nvarchar

## DetObjQualifierSetItem
- PK: Key
- Rows: 177
- Purpose: Supporting lookup/configuration table used by drawing-style processing.
- Columns (sample): Key:int, ObjQualifier:int, ModelRole:nvarchar, Filter:nvarchar, IdDetObjQualifierSet:int

## DetObjReprMapItems
- PK: Key, Order
- Rows: 54
- Purpose: Annotation/appearance rules consumed by style rendering.
- Columns (sample): Key:int, Order:int, Description:int, OwnerText:nvarchar, ObjQualifier:int, GeometricRestrictions:int, …

## DetObjReprMapsNew
- PK: Key
- Rows: 1
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, OwnerText:nvarchar, Items:int

## DetProcessesSuiteDefinition
- PK: Key
- Rows: 0
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, SuiteItems:int, OwnerText:nvarchar

## DetProcessesSuiteItems
- PK: Key, Order
- Rows: 0
- Purpose: Supporting lookup/configuration table used by drawing-style processing.
- Columns (sample): Key:int, Order:int, Process:int, ObjectSelection:int, OwnerText:nvarchar

## DetViewArrangeStrategy
- PK: Key
- Rows: 1
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, ViewDistance:float, ArrangeCutsInChains:bit, OwnerText:nvarchar

## DetViewDimPointSelection
- PK: Key
- Rows: 2
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, Objects:int, GeometricRestrictions:int, DepthPosition:int, VisibilityStatus:int, …

## DetViewDimRequestLinear
- PK: Key
- Rows: 2
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, OwnerText:nvarchar, Direction:int, ArrangeGlobally:bit, ArrangeAbove:bit, …

## DetViewDimRequestLinearGroup
- PK: Key
- Rows: 1
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, BitmapId:int, BitmapImage:nvarchar

## DetViewDimStrategyItems
- PK: Key, Order
- Rows: 2
- Purpose: Request/selection strategy rows used when building detail views and dimensions.
- Columns (sample): Key:int, Order:int, Description:nvarchar, OwnerText:nvarchar, Type:int, RequestLinear:int, …

## DetViewDimStrategyNew
- PK: Key
- Rows: 1
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, OwnerText:nvarchar, OneChainPerBoltDiam:int, Items:int

## DetViewLengthClip
- PK: Key
- Rows: 1
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, X Clip:int, Y Clip:int, MinRemainingLength:float, MinClipIntervalLength:float, …

## DetViewRequest
- PK: Key
- Rows: 1
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, SystemAndBox:int, ObjReprMap:int, DefaultObjAppearance:int, SelectMode:int, …

## DetViewRequestCategories
- PK: Key
- Rows: 1
- Purpose: Request/selection strategy rows used when building detail views and dimensions.
- Columns (sample): Key:int, Category:int, DetViewRequest:int

## DetViewSystemAndBox
- PK: Key
- Rows: 1
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, SystemSource:int, xyMode:int, xDelta:float, yDelta:float, …

## DetailFilenameSelector
- PK: Key
- Rows: 0
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, OwnerText:nvarchar, Prototype:nvarchar, Prefix:nvarchar, OnNextObject:int, …

## DetailMasterTable
- PK: Key, BaseCategory, SubCategory, StyleKey
- Rows: 1
- Purpose: Master lookup for detail components used by style/process rows.
- Columns (sample): Key:int, BaseCategory:int, SubCategory:int, StyleKey:int, RunName:nvarchar, OwnerText:nvarchar, …

## DetailProcessCategories
- PK: Key
- Rows: 0
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, OwnerText:nvarchar, Image:nvarchar, ImageInactive:nvarchar

## DetailProcessDefinition
- PK: Key
- Rows: 0
- Purpose: Defines process templates used by detail style generation.
- Columns (sample): Key:int, RunName:nvarchar, Category:int, OwnerText:nvarchar, AvailableInDSVault:bit, ExamplePicture:nvarchar, …

## DetailProcessMain2CutScale
- PK: Key
- Rows: 0
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, OwnerText:nvarchar, Number of items:int, MainViewScale1:float, Request1:float, …

## DetailProcessScales
- PK: Key
- Rows: 0
- Purpose: Named style/configuration table used by drawing-style authoring workflows.
- Columns (sample): Key:int, RunName:nvarchar, OwnerText:nvarchar

## DetailProcessScalesItem
- PK: Key
- Rows: 0
- Purpose: Request/selection strategy rows used when building detail views and dimensions.
- Columns (sample): Key:int, Request:float, DetProcScaleId:int

## DetailProcessStep
- PK: Key
- Rows: 0
- Purpose: Ordered steps per detail process definition.
- Columns (sample): Key:int, RunName:nvarchar, Category:int, OwnerText:nvarchar, CoordSystemSelector:int, FilenameSelector:int, …

## DetailStyle
- PK: Key
- Rows: 1
- Purpose: Root drawing style records keyed by style Key; referenced by style maps and view/annotation strategy tables.
- Columns (sample): Key:int, RunName:nvarchar, ViewArrangeStrategy:int, DetailOrientation:int, ObjectSelectionStrategy:int, TitleFormat:nvarchar, …

## DetailStyleMapItems
- PK: Key, Order
- Rows: 0
- Purpose: Style map line items connecting DetailStyle maps to process steps and requests.
- Columns (sample): Key:int, Order:int, Script:nvarchar, ObjQualifierSet:int, DetailStyle:int, DetailStyleOverrides:int

## DetailStyleMapNew
- PK: Key
- Rows: 0
- Purpose: Maps style to process/request categories for generated detail views.
- Columns (sample): Key:int, RunName:nvarchar, UseSinglepartStyleOfModelobject:bit, UseMainpartStyleOfModelobject:bit, OwnerText:nvarchar, Items:int
