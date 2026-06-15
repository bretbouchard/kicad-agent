# KiCad Agent Reference

**Distilled from:** KiCad 10.99 Schematic Editor Reference Manual


Rules and conventions that AI agents must follow when editing KiCad schematics. Each section is a single-sentence summary followed by key details.


---

## Grids and snapping

Schematic elements such as symbols, wires, text, and graphic lines are snapped to the grid
when moving, dragging, and drawing them. Additionally, the wire and label tools snap to other
connected items such as pins, wires, and labels even when grid snapping is disabled.
Both grid and connected object snapping can be disabled while moving the mouse by using the
modifier keys in the table below.
On Apple keyboards, use the
Modifier Key
Cmd
key instead of
Ctrl
Effect
Ctrl
Disable grid snapping.
Shift
Disable connected object snapping.
The default grid size is 50 mil (0.050") or 1.27 millimeters. This is the recommended grid for
placing symbols and wires in a schematic and for placing pins when designing a symbol in the
Symbol Editor. Smaller grids can also be used, but this is intended only for text and symbol
graphics, and not recommended for placing pins and wires.
Wires connect with other wires or pins only if their ends coincide exactly.
Therefore it is very important to keep symbol pins and wires aligned to the
grid. It is recommended to always use a 50 mil grid when placing symbols and
drawing wires because the KiCad standard symbol library and all libraries that
follow its style also use a 50 mil grid. Using a grid size other than 50 mil will
result in schematics without proper connectivity!
Symbols, wires, and other elements that are not aligned to the grid can be
snapped back to the grid by selecting them, right clicking, and clicking Align
Elements to Grid.
You can adjust the grid size by right-clicking and selecting a new grid from the list in the Grid
submenu. Pressing the n or N hotkeys will cycle to the next and previous grid in the list,
respectively.
You can also select a new grid or edit the available grids in the Grids pane of the preferences
dialog. As a shortcut to reach this dialog, right click the
button on the left toolbar and select
Edit Grids….
In this dialog you can select an active grid from the list of grids, reorder the list of grids ( / ),
and add ( ), remove ( ), or edit ( ) grids. Grids defined in this dialog can have unequal X and
Y spacing as well as an optional name. The grid spacing and name are specified when you
create or edit a grid.
This dialog also lets you designate two grids from the list as "Fast Grids", which can be quickly
selected using Alt + 1 and Alt + 2 .
Finally, you can configure grid overrides for different types of objects. Grid overrides let you set
particular grid sizes for different types of objects which will be used instead of the default grid
when working with those objects. For example, you can set a 50 mil grid for wires and
connected items while using smaller grids to finely position text and graphics. Grid overrides
can be individually enabled and disabled in this dialog, or globally enabled and disabled using
the
button on the left toolbar ( Ctrl + Shift + G ).
The visual appearance of the grid can also be customized in several ways. You can change the
thickness of the grid markings, switch their shape (dots, lines, or crosses), and set the minimum
displayed spacing in the Display Options page of the preferences dialog, and you can change
the grid color in the Colors page of the preferences dialog.
The grid can be shown or hidden using the
button on the left-hand toolbar. By default the
grid is still active even if it is hidden, but this is configurable in the Display Options preferences
page. There you can set the grid to be disabled when it is hidden or even disable the grid
entirely.

---

## Editing object properties

All objects have properties that are editable in a dialog. Use the hotkey E or select Properties
from the right-click context menu to edit the properties of selected item(s). You can only open
the properties dialog if all the items you have selected are of the same type. For many object
types, like symbols, you can only edit the properties of a single item at one time. To edit the
properties of multiple items at once, including items with different types, you can use the
Properties Manager.
You can only use the properties dialog to edit one item at a time. To edit multiple items, use the
Properties Manager, described below. There are also other tools that can be used to edit
specific types of objects in bulk, such as the Edit Text and Graphics tool for editing visual
properties of text, symbol fields, labels, and graphic shapes, or the Symbol Fields Table for
editing symbol fields in bulk.
You can also view and edit item properties using the Properties Manager. The Properties
Manager is a docked panel that displays the properties of the selected item or items for editing.
If multiple types of items are selected at once, the properties panel displays only the properties
shared by all of the selected item types.
Editing a property in the Properties Manager immediately applies the change. When multiple
items are selected, property modifications are applied to each selected item individually, not to
the whole selection as a group. For example, when changing the orientation of multiple items,
each item is individually rotated around its own origin, not the group’s origin.
Show the Properties Manager with View → Panels → Properties or the
button on the left
toolbar.
In properties dialogs and many other dialogs, any field that contains a numeric value can also
accept a basic math expression that results in a numeric value.
For example, a dimension may be entered as 2 * 2mm , resulting in a value of 4mm . Basic
arithmetic operators as well as parentheses for defining order of operations are supported.
Units can also be specified, and unit conversions are performed automatically, so 1in + 1mm
evaluates to 26.4mm .

---

## Working with symbols

Placing symbols
To place a symbol in your schematic, use the
button or the
hotkey. The Choose Symbols
dialog appears and lets you select a symbol to add. Symbols are grouped by symbol library.

---

## Reference designators and symbol annotation

Reference designators are unique identifiers for components in a design. They are often
printed on a PCB and in assembly diagrams, and allow you to match symbols in a schematic to
the corresponding components on a board.
In KiCad, reference designators consist of a letter indicating the type of component ( R for
resistor, C for capacitor, U for IC, etc.) followed by a number. If the symbol has multiple units
then the reference designator will also have a trailing letter indicating the unit. Symbols that
don’t have a reference designator set have a ? character instead of the number. Reference
designators must be unique.
Reference designators can be automatically set when symbols are added to the schematic, and
you can set or reset reference designators yourself by manually editing an individual symbol’s
reference designator field or in bulk using the Annotation tool.
The process of setting a symbol’s reference designator is called annotation.
Auto-annotation
When auto-annotation is enabled, symbols will be automatically annotated when they are
added to the schematic. You can enable auto-annotation by checking the Automatically
annotate symbols checkbox in the Schematic Editor → Editing Options pane in
Preferences. Auto-annotation can also be toggled using the
button in the left toolbar.
There are options to control how symbols are automatically annotated in the Annotation page
of Schematic Setup.
When multiple symbols are added simultaneously, they are annotated according to the
Order setting, sorted by either X or Y position.
The Numbering option sets the starting number for new reference designators. This can
be the lowest available number, or a number based on the sheet number. When Allow
reference reuse is enabled, reference designators can be automatically assigned as long
as they are not currently used by another symbol. When disabled, a reference designator
can never be used again once it has been assigned to a symbol, even if it is not currently
in use.
For more information about annotation options, see the documentation for the Annotation
page of Schematic Setup.
Annotation tool
The Annotation tool assigns reference designators to symbols in the schematic. To launch the
Annotation tool, click the
button in the top toolbar.
The tool provides several options to control how symbols are annotated.
Scope: Selects whether annotation is applied to the entire schematic, to only the current sheet,
or to only the selected symbols. If the Recurse into subsheets option is selected, symbols in
subsheets of the selected scope will be reannotated; otherwise symbols in subsheets will not
be reannotated. For example, if Recurse into subsheets and Selection only selected, symbols
in any selected subsheets will be reannotated.
Options: Selects whether annotation should apply to all symbols and reset existing reference
designators, or apply only to unannotated symbols. If the Reset symbol units option is
enabled, symbol units will be reannotated individually. This means symbol units may be
grouped into symbols differently after reannotation. When it is disabled, each symbol’s units
will be reannotated as a group so that they remain together as units of the same symbol.
Order: Chooses the direction of numbering. If symbols are sorted by X position, all symbols on
the left side of a schematic sheet will be lower numbered than symbols on the right side of the
sheet. If symbols are sorted by Y position, all symbols on the top of a sheet will be lower
numbered than symbols at the bottom of the sheet.
Numbering: Selects the starting point for numbering reference designators. The lowest
unused number above the starting point is picked for each reference designator. The starting
point can be an arbitrary number (typically zero), or it can be the sheet number multiplied by
100 or 1000 so that each part’s reference designator corresponds to the schematic page it is
on.
The Clear Annotation button clears all reference designators in the selected scope.
Annotation messages can be filtered with the checkboxes at the bottom or saved to a report
using the Save… button.

---

## Text variables

Text variables can be created in the Text Variables section. KiCad will substitute the variable
name with the text string assigned to the variable. This substitution happens anywhere the
variable name is used inside the variable replacement syntax of ${VARIABLENAME} .
For example, you could create a variable named VERSION and set the text substitution to
1.0 . Now, in any text object in the schematic, you can enter ${VERSION} and KiCad will
display this as 1.0 . If you change the value to 2.0 , every text object that includes
${VERSION} will be updated automatically. You can also mix regular text and variables. For
example, you can create a text object with the text Version: ${VERSION} which will be
displayed as Version: 1.0 .
Text variables can also be created in Board Setup. Text variables are project-wide; variables
created in the schematic editor are also available in the board editor, and vice versa.
There are also a number of built-in system text variables.
Embedding files
External files can be embedded within a schematic. Embedding a file stores a copy of the file
inside the schematic file. The design can then refer to the embedded copy of the file instead of
the external file, which makes the project more portable as it doesn’t rely on an external file.
Fonts, datasheets, drawing sheets, SPICE models, and footprint 3D models can be embedded
and used within KiCad. Other arbitrary files can also be embedded to store them in the project
for later export, but they are not used by any KiCad functionality. Files embedded in a
schematic necessarily increase the schematic’s file size, although files are compressed before
being embedded to minimize the space required.
Embedded files are managed in the Embedded Files section of Schematic Setup. All files
embedded in a schematic are shown here. To embed a file inside a schematic, click the
button and select the file. The file is then embedded inside the schematic and is listed in the
embedded files list along with its embedded reference. The embedded reference is a unique
identifier for the embedded file that begins with kicad-embed:// . You can use the embedded
reference elsewhere in the Schematic Editor to refer to the embedded file as if it were an
external file path. You can copy the embedded reference by right clicking and selecting Copy
Embedded Reference. To remove an embedded file, click the button. Any remaining links to
the removed file will become invalid.
Datasheets, SPICE models, and drawing sheets can be embedded directly
using the file browser when you add them to a symbol (datasheets and SPICE
models) or to a schematic (drawing sheets) by enabling the Embed Files
option in the file browser. This is a single-step shortcut for adding the files in
Schematic Setup and then referring to them by their embedded reference; the
result is the same.
To embed any fonts used in a schematic, check the Embed fonts checkbox. All fonts used in
the schematic will be embedded, so text using that font can be edited on any computer
regardless of whether the font file is installed.
You can also embed files in a symbol. Such files will be available within the symbol, but not
within the larger schematic or in other symbols. Files embedded in a symbol are deduplicated
when the symbol is added to a schematic: if a file is embedded in a symbol, and multiple
instances of that symbol are added to the schematic, only one copy of the file will be
embedded, and all of the symbol instances will refer to the same embedded file.
As an example, to embed a datasheet in a project and use it within several symbols, you could
embed the datasheet using the schematic setup dialog, copy the internal reference, and paste
the internal reference into the datasheet field of each symbol that uses that datasheet. Each
symbol would then have a portable reference to the embedded datasheet. Alternatively, you
could embed the datasheet within the library symbol. In this case, each symbol will already
have the datasheet embedded when the symbol is added to a schematic. A more convenient
way to achieve the same thing, however, is to open the symbol’s properties dialog, browse for a
datasheet file, and enable the Embed File option in the file browser. Again, this could be done
for a symbol in the schematic or for a symbol in the source symbol library.
Files can also be embedded in boards.
Importing settings
You can import some or all of the schematic setup from an existing schematic. This allows you
to choose a schematic to use as a template and select which settings to import.
To import settings, click the Import Settings from Another Project… button at the bottom of
the Schematic Setup dialog and then choose the .kicad_sch file you want to import from.
Select which settings you want to import and the current settings will be overwritten with the
values from the chosen schematic.
The settings that are available to import are:
Formatting preferences
Annotation preferences
Field name templates
BOM presets
BOM format presets
Violation severities
Pin conflict map

---

## Electrical connections between sheets

Electrical connections between sheets are made with labels. There are several kinds of labels in
KiCad, each with a different connection scope.
Local labels only make connections within a sheet. Therefore local labels cannot be used
to connect between sheets. Local labels are added with the
button.
Global labels make connections anywhere in a schematic, regardless of sheet. Therefore
global labels can be used to make connections between sheets whether the sheets are
top-level or hierarchical. Global labels are added with the
button.
Hierarchical labels in a hierarchical subsheet connect to hierarchical sheet pins
accessible in the parent sheet. Hierarchical designs rely on hierarchical labels and pins to
make connections between parent sheets and child sheets. You can think of sheet pins as
defining the interface for a subsheet; hierarchical labels within the child sheet connect to
corresponding sheet pins which are visible in the parent sheet. Hierarchical labels are
added inside a child sheet using the
button.
Labels that have the same name will connect, regardless of the label type, if
Hidden power pins can also be considered global labels, because they connect
they are in the same sheet.
anywhere in the schematic hierarchy.
Hierarchical sheet pins
After placing hierarchical labels within a subsheet, matching hierarchical sheet pins can be
added to the subsheet symbol in the parent sheet. You can then make connections to the
hierarchical pins with wires, labels, and buses. Hierarchical sheet pins in a subsheet symbol are
connected to the matching hierarchical labels in the subsheet itself.
Hierarchical labels must be defined in the subsheet before the corresponding
hierarchical sheet pin can be imported in the sheet symbol.
For every hierarchical label in the subsheet, add the corresponding hierarchical pin onto the
sheet symbol by clicking the
button in the right toolbar, then clicking on the sheet symbol. A
sheet pin for the first unmatched hierarchical label will be attached to the cursor, where it can
be placed anywhere along the border of the sheet symbol. Clicking again with the tool will
continue to add additional sheet pins until all of the hierarchical labels in the subsheet have a
matching sheet pin on the sheet symbol. Sheet pins can also be imported by selecting Place
Sheet Pin in a sheet symbol’s right-click context menu.
You can edit the properties of a sheet pin in the Sheet Pin Properties dialog. Open this dialog by
double-clicking a sheet pin, selecting a sheet pin and using the E hotkey, or right-clicking a
sheet pin and selecting Properties….
The sheet pin’s name can be edited in the textbox or by selecting from the dropdown list of
hierarchical labels in the subsheet. A sheet pin’s name has to match the corresponding
hierarchical label in the subsheet, so if you change a pin name you must change the label name
as well.
Shape changes the shape of the sheet pin, and has no electrical effect. It can be set to Input,
Output, Bidirectional, Tri-state, or Passive. The pin’s font, text size, color, and emphasis (bold
or italic) can also be changed.
Syncing sheet pins
Another way to manage the connections between hierarchical labels and sheet pins is to use
the Sync Sheet Pins tool. Launch this tool using the
button in the right toolbar or with Sync
Sheet Pins in a sheet symbol’s right click context menu.
This dialog shows the hierarchical labels and hierarchical sheet pins for each hierarchical sheet.
If the tool was launched from the context menu of a sheet symbol, only one tab will be
available, with the labels and sheet pins for that specific sheet. If the tool was started globally,
i.e. with the
button or with Place → Sync Sheet Pins, a tab will be shown for each
hierarchical sheet. If a sheet was selected in the editing canvas when the tool was launched, the
dialog will open to that sheet’s tab.
The icon in each tab indicates whether the hierarchical sheet pins on the sheet symbol are
correctly matched with the hierarchical labels inside the sheet. If the tab has a icon, then
there is a hierarchical label in the sheet without a matching sheet pin, or a sheet pin without a
corresponding hierarchical label, or both. If the tab has a icon, then the hierarchical labels
and hierarchical sheet pins are matched up correctly. Sheet pins and labels are considered
matching if they have the same name and the same graphic shape (input, output, bidirectional,
tri-state, or passive).
The column on the left lists sheet pins for the current sheet that do not have a corresponding
hierarchical label in the sheet. The middle column lists hierarchical labels in the current sheet
that do not have a corresponding hierarchical sheet pin on the sheet symbol. The right column
lists pairs of matching sheet pins and hierarchical labels. The name of each pin or label is
shown along with its graphic shape.
If you click the Add Hierarchical Labels button, new hierarchical labels corresponding to the
selected sheet pins will be created for you to place sequentially in the sheet. The selected sheet
pins are then removed from the left column and added to to the right column for matching
sheet pins and labels. Clicking Delete Sheet Pins will delete the selected sheet pins from the
sheet symbol.
If you click the Add Sheet Pins button, new sheet pins corresponding to the selected
hierarchical labels will be created for you to place on the sheet symbol. The hierarchical labels
are then removed from the middle column and added to the right column for matching sheet
pins and labels. Clicking Delete Hierarchical Labels will delete the selected hierarchical labels
from inside the sheet.
Clicking the button will match the selected sheet pin and hierarchical label by renaming the
sheet pin to match the hierarchical label’s name. Clicking the button will do the opposite,
matching the selected sheet pin and hierarchical label by renaming the label to match the
sheet pin.
Clicking the button will unmatch a matched pair, moving both the sheet pin and the
hierarchical label back to their respective unmatched columns. The unmatched sheet pin and
hierarchical label can then be edited or rematched as desired.
Any changes made in the Sync Sheet Pins dialog are applied immediately, before the dialog is
closed. To cancel a change made in the Sync Sheet Pins dialog, use Undo.

---

## Assigning Footprints in Symbol Properties

A symbol’s Footprint field can be edited directly in the symbol’s Properties window.
Clicking the button in the Footprint field opens the Footprint Chooser, which shows the
available footprints sorted by footprint libraries.
The Footprint Chooser filters footprints by name, description, and keywords, as well as any
fields that are shown as columns, according to what you type into the search field. * and ?
wildcards are available. The footprint search behaves the same as in the symbol chooser
dialog. You can choose to sort search results alphabetically or by best match using the options
in the menu.
If the symbol defines any footprint filters, the apply footprint filters option can be used to
hide footprints that don’t match those filters. If the filter by pin count option is selected, only
footprints that match the symbol’s pincount will be listed.
Single clicking a footprint name selects the footprint, shows its name, description, and
keywords in the bottom pane, and displays it in the preview pane on the right. Clicking the
button shows or hides the description pane. You can show and hide 2D and 3D previews of the
footprint by clicking the and buttons (Show 3D viewer in own window causes the 3D
preview to be opened in a new window).
Double clicking on a footprint closes the chooser and sets the symbol’s Footprint field to the
selected footprint.
Assigning Footprints with the Symbol Fields Table
Rather than editing the properties of each symbol individually, the Symbol Fields Table can be
used to view and edit the properties of all symbols in the design in one place. This includes
assigning footprints by editing the Footprint field of each symbol.
The Symbol Fields Table is accessed with Tools → Edit Symbol Fields…, or with the
button
on the top toolbar.
The Footprint field behaves the same here as in the Symbol Properties window: it can be
edited directly, or footprints can be selected visually with the Footprint Library Browser.
For more information on the Symbol Fields Table, see the section on editing symbol properties.

---

## Forward and back annotation

Update PCB from Schematic (forward annotation)
Use the Update PCB from Schematic tool to sync design information from the Schematic Editor
to the Board Editor. The tool can be accessed with Tools → Update PCB from Schematic ( F8 )
in both the schematic and board editors. You can also use the
icon in the top toolbar of the
Board Editor. This process is often called forward annotation.
Update PCB from Schematic is the preferred way to transfer design
information from the schematic to the PCB. In older versions of KiCad, the
equivalent process was to export a netlist from the Schematic Editor and
import it into the Board Editor. It is no longer necessary to use a netlist file.
The tool adds the footprint for each symbol to the board and transfers updated schematic
information to the board. In particular, the board’s net connections are updated to match the
schematic. Symbols with the Exclude from board attribute are not transferred to the PCB.
The changes that will be made to the PCB are listed in the Changes To Be Applied pane. The PCB
is not modified until you click the Update PCB button.
You can show or hide different types of messages using the checkboxes at the bottom of the
window. A report of the changes can be saved to a file using the Save… button.
Options
The tool has several options to control its behavior.
Option
Description
Re-link footprints to
schematic symbols based on
their reference designators
Footprints are normally linked to schematic symbols via a
unique identifier created when the symbol is added to the
schematic. A symbol’s unique identifier cannot be changed,
but will be lost when the symbol is deleted, even if a symbol
with the same reference designator replaces it.
If checked, each footprint in the PCB will be re-linked such
that each footprint has its unique identifier updated to
match the symbol that has the same reference designator
as the footprint.
This option should generally be left unchecked. See below
for more details on when to use this option.
Group footprints based on
symbol group
If checked, footprints will be added to groups in the PCB if
their linked symbols are grouped.
Replace footprints with
those specified by symbols
If checked, footprints in the PCB will be replaced with the
footprint that is specified in the corresponding schematic
symbol.
If unchecked, footprints that are already in the PCB will not
be changed, even if the schematic symbol is updated to
specify a different footprint.
Delete footprints with no
symbols
If checked, any footprint in the PCB without a corresponding
symbol in the schematic will be deleted from the PCB.
Footprints with the "Not in schematic" attribute will be
unaffected.
If unchecked, footprints without a corresponding symbol will
not be deleted.
Override locks
If checked, locking a footprint will not affect whether a
footprint is deleted or replaced based on changes in the
schematic.
If unchecked, locked footprints will never be deleted or
replaced even if they otherwise would be.
Update footprint fields from
symbols
If checked, new and updated fields in symbols will be
transferred to the corresponding footprints, keeping symbol
and footprint fields in sync.
If unchecked, footprint fields will not be updated when fields
change in the corresponding symbols.
Remove footprint fields not
found in symbols
If checked, footprint fields will be removed if they do not
exist in the corresponding symbol.
If unchecked, footprint fields that do not exist in the
corresponding symbol will not be removed, allowing
footprints to have additional fields compared to the
corresponding symbols.
Re-linking symbols and footprints
Symbols and footprints are linked together using unique identifiers (also called UUIDs). These
are handled automatically within KiCad and are not usually visible to users. They allow a
symbol and its partner footprint to keep their connection between schematic and PCB, even if
the reference designator is changed. New objects get assigned their identifiers upon creation.
Re-linking by unique identifier (default)
In normal use, the Re-link footprints to schematic symbols based on their reference
designators option should be unchecked. In this mode, symbols with the same identifier as a
footprint will update that footprint, regardless of the reference designator. Symbols which have
an identifier that doesn’t match any footprint will add a new footprint linked to that identifier.
For example, in the below schematic, both R1 and R2 are linked via their unique IDs to
footprints on the PCB:
If symbol reference designators are changed in the schematic (e.g. by re-annotation), running
the Update PCB from Schematic process will update the reference designators on the PCB.
Re-linking by reference designator
If the checkbox is checked, the linking process is done using the reference designators. This can
be useful for workflows that result in a symbol being deleted and replaced by another one,
rather than being updated in-place. For example, cut-and-pasting a block of schematic or a
sheet and copy-pasting and re-annotating will usually break the identifier-based links.
For example in the below case, the resistors R1 and R2 have been deleted and replaced, then
re-annotated. While the reference designators are the same, the internal identifiers have
changed. Updating the PCB by identifier would cause the existing footprints to be deleted and
new ones added - to KiCad, the existing footprints have no matching symbol. This would cause
the footprints to lose their positions and need placing again.
Re-linking the footprints by reference designator causes KiCad to re-create the links, using the
matching reference designators as a guide.
Because the links have been re-established, the next forward annotation should use the
normal identifier-based linking (i.e. the checkbox should be unchecked).
Update Schematic from PCB (back annotation)
The typical workflow in KiCad is to make changes in the schematic and then sync the changes
to the board using the Update PCB From Schematic tool. However, the reverse process is also
possible: design changes can be made in the board and then synced back to the schematic
using Tools → Update Schematic From PCB in either the schematic or board editors. This
process is also known as backannotation.
The tool syncs changes in reference designators, values, attributes (like DNP or Exclude From
BOM), footprint assignments, other fields, and net names from the board to the schematic.
Each type of change can be individually enabled or disabled.
The changes that will be made to the schematic are listed in the Changes To Be Applied pane.
The schematic is not modified until you click the Update Schematic button.
You can show or hide different types of messages using the checkboxes at the bottom of the
window. A report of the changes can be saved to a file using the Save… button.
Options
The tool has several options to control its behavior.
Option
Description
Re-link footprints to
schematic symbols based on
their reference designators
If checked, each footprint in the PCB will be re-linked to the
symbol that has the same reference designator as the
footprint. This option is incompatible with updating symbol
reference designators.
If unchecked, footprints and symbols will be linked by
unique identifier as usual, rather than by reference
designator.
This option should generally be left unchecked. See the PCB
Editor documentation for more details on when to use this
option.
Reference designators
If checked, symbol reference designators will be updated to
match the reference designators of the linked footprints.
If unchecked, symbol reference designators will not be
updated.
Values
If checked, symbol values will be updated to match the
values of the linked footprints.
If unchecked, symbol values will not be updated.
Attributes
If checked, symbol attributes (like exclude from BOM and
DNP) will be updated to match the corresponding attributes
of the linked footprints.
If unchecked, symbol attributes will not be updated.
Other fields
If checked, other symbol fields will be updated to match the
corresponding fields of the linked footprints. Reference
designator, value, and footprint are each controlled by their
own separate option.
If unchecked, other fields will not be updated in the
schematic.
Footprint assignments
If checked, footprint assignments will be updated for
symbols which have had their footprints changed or
replaced in the board.
If unchecked, symbol footprint assignments will not be
updated.
Net names
If checked, the schematic will be updated with any net name
changes that have been made in the board. Net labels will
be updated or added to the schematic as necessary to
match the board.
If unchecked, net names will not be updated in the
schematic.
Prefer symbol unit swaps
over label swaps
The tool will detect situations where net connections within
a multi-unit symbol have changed due to entire symbol units
(gates) being swapped. Such swaps will be detected whether
they were performed using the PCB Editor’s gate swap tool
or whether the equivalent net changes were made
manually.
If checked, in these situations the schematic will be updated
to match the PCB by swapping symbol units rather than
swapping the net labels attached to the pins on each symbol
unit.
If unchecked, symbol unit swaps will be represented in the
schematic by swapping net labels rather than swapping
symbol units.
Prefer symbol pin swaps
over label swaps
The tool will detect situations where net connections have
swapped between two pins within a symbol. Such swaps will
be detected whether they were performed using the pin
swap tool or whether the equivalent net changes were
made manually.
If checked, in these situations the schematic will be updated
to match the PCB by swapping symbol pins in the symbol
rather than swapping the net labels attached to the pins, if
possible. Symbol pins can only be swapped if the Allow
unconstrained pin swaps option is enabled in the Editing
Options page of the Schematic Editor’s preferences.
If unchecked, symbol pin swaps will be represented in the
schematic by swapping net labels rather than swapping pins
in the symbol.
The Geographical Reannotation feature can be used in combination with
backannotating reference designators to reannotate all components in the
design based on their location in the layout.
Back annotation with CMP files
Select changes can also be synced from the PCB back to the schematic by exporting a CMP file
from the PCB editor (File → Export → Footprint Association (.cmp) File…) and importing it in
the Schematic Editor (File → Import → Footprint Assignments…).
This method can only sync changes made to footprint assignments and
footprint fields. It is recommended to use the Update Schematic from PCB tool
instead.

---

## Generating a Netlist

A netlist is a file which describes electrical connections between symbol pins. These
connections are referred to as nets. Netlist files contain:
A list of symbols and their pins.
A list of connections (nets) between symbol pins.
Many different netlist formats exist. Sometimes the symbols list and the list of nets are two
separate files. This netlist is fundamental in the use of schematic capture software, because the
netlist is the link with other electronic CAD software, such as PCB layout software, simulators,
and programmable logic compilers.
KiCad supports several netlist formats:
KiCad format, which can be imported by the KiCad PCB Editor. However, the "Update PCB
from Schematic" tool should be used instead of importing a KiCad netlist into the PCB
editor.
OrCAD PCB2 format, for designing PCBs with OrCAD.
Allegro format, for designing PCBs with Allegro.
PADS format, for designing PCBs with PADS.
CADSTAR format, for designing PCBs with CADSTAR.
Spice format, for use with various external circuit simulators.
In KiCad version 5.0 and later, it is not necessary to create a netlist for
transferring a design from the schematic editor to the PCB editor. Instead, use
the "Update PCB from Schematic" tool.
Other software tools that use netlists may have restrictions on spaces and
special characters in component names, pins, nets, and other fields. For
compatibility, be aware of such restrictions in other tools you plan to use, and
name components, nets, etc. accordingly.
Netlist formats
Netlists are exported with the Export Netlist dialog (File→Export→Netlist…).
KiCad supports exporting netlists in several formats: KiCad, OrcadPCB2, Allegro, PADS,
CADSTAR, Spice, and Spice Model. Each format can be selected by selecting the corresponding
tab at the top of the window. Some netlist formats have additional options.
Clicking the Export Netlist button prompts for a netlist filename and saves the netlist.
Netlist generation can take up to several minutes for large schematics.
Custom generators for other netlist formats can be added by clicking the Add Generator…
button. Custom generators are external tools that are called by KiCad, for example Python
scripts or XSLT stylesheets. For more information on custom netlist generators, see the section
on adding custom netlist generators.
Spice Netlist Format
The Spice netlist format offers several options.
When the use current sheet as root is selected, only the current sheet is exported to a
subcircuit model. Otherwise, the entire schematic sheet is exported.
The Save all voltages option adds a .save all command to the netlist, which causes
the simulator to save all node voltages.
The Save all currents option adds a .probe alli command to the netlist, which causes
the simulator save all node currents.
The Save all power dissipations adds .probe commands to save the power dissipation
in each component.
The Save all digital event data removes the esave none command from the netlist,
which causes digital event data to be saved. Digital event data may consume a lot of
memory.
Exact behavior may vary between simulation tools.
Passive symbol values are automatically adjusted to be compatible with various Spice
simulators. Specifically:
μ and M as unit prefixes are replaced with u and Meg , respectively
Units are removed (e.g. 4.7kΩ is changed to 4.7k )
Values in RKM format are rewritten to be Spice-compatible (e.g. 4u7 is changed to 4.7u )
The Spice netlist exporter also provides an easy way to simulate the generated netlist with an
external simulator. This can be useful for running a simulation without using KiCad’s internal
ngspice simulator, or for running an ngspice simulation with options that are not supported by
KiCad’s simulator tool.
Enter the path to the external simulator in the text box, with %I representing the generated
netlist. Check the run external simulator command box to generate the netlist and
automatically run the simulator.
The default simulator command ( spice "%I" ) must be adjusted to point to a
simulator installed on your system.
Spice simulators expect simulation commands ( .PROBE , .AC , .TRAN , etc.) to be included in
the netlist. Any text line included in the schematic diagram starting with a period ( . ) will be
included in the netlist. If a text object contains multiple lines, only the lines beginning with a
period will be included.
.include directives for including model library files are automatically added to the netlist
based on the Spice model settings for the symbols in the schematic.
Spice Model Netlist Format
KiCad can also export a netlist of the schematic as a Spice subcircuit model, which can be
included in a separate Spice simulation. Any hierarchical labels in the schematic are used as
pins for the subcircuit model. Each pin in the model is annotated with a comment describing
the pin’s electrical direction:
Input hierarchical labels are mapped to an input annotation
Output hierarchical labels are mapped to an output annotation
Bidirectional hierarchical labels are mapped to an inout annotation
Tri-state hierarchical labels are mapped to a tristate annotation
Passive hierarchical labels are mapped to a passive annotation
When the use current sheet as root is selected, only the current sheet is exported to a
subcircuit model. Otherwise, the entire schematic sheet is exported.
Netlist examples
Below is the schematic from the sallen_key project included in KiCad’s simulation demos.
The KiCad format netlist for this schematic is as follows:
(export (version "E")
(design
(source "/usr/share/kicad/demos/simulation/sallen_key/sallen_key.kicad_sch")
(date "Sun 01 May 2022 03:14:05 PM EDT")
(tool "Eeschema (6.0.4)")
(sheet (number "1") (name "/") (tstamps "/")
(title_block
(title)
(company)
(rev)
(date)
(source "sallen_key.kicad_sch")
(comment (number "1") (value ""))
(comment (number "2") (value ""))
(comment (number "3") (value ""))
(comment (number "4") (value ""))
(comment (number "5") (value ""))
(comment (number "6") (value ""))
(comment (number "7") (value ""))
(comment (number "8") (value ""))
(comment (number "9") (value "")))))
(components
(comp (ref "C1")
(value "100n")
(libsource (lib "sallen_key_schlib") (part "C") (description ""))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-00005789077d"))
(comp (ref "C2")
(value "100n")
(fields
(field (name "Fieldname") "Value")
(field (name "SpiceMapping") "1 2")
(field (name "Spice_Primitive") "C"))
(libsource (lib "sallen_key_schlib") (part "C") (description ""))
(property (name "Fieldname") (value "Value"))
(property (name "Spice_Primitive") (value "C"))
(property (name "SpiceMapping") (value "1 2"))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-00005789085b"))
(comp (ref "R1")
(value "1k")
(fields
(field (name "Fieldname") "Value")
(field (name "SpiceMapping") "1 2")
(field (name "Spice_Primitive") "R"))
(libsource (lib "sallen_key_schlib") (part "R") (description ""))
(property (name "Fieldname") (value "Value"))
(property (name "SpiceMapping") (value "1 2"))
(property (name "Spice_Primitive") (value "R"))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-0000578906ff"))
(comp (ref "R2")
(value "1k")
(fields
(field (name "Fieldname") "Value")
(field (name "SpiceMapping") "1 2")
(field (name "Spice_Primitive") "R"))
(libsource (lib "sallen_key_schlib") (part "R") (description ""))
(property (name "Fieldname") (value "Value"))
(property (name "SpiceMapping") (value "1 2"))
(property (name "Spice_Primitive") (value "R"))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-000057890691"))
(comp (ref "U1")
(value "AD8051")
(fields
(field (name "Spice_Lib_File") "ad8051.lib")
(field (name "Spice_Model") "AD8051")
(field (name "Spice_Netlist_Enabled") "Y")
(field (name "Spice_Primitive") "X"))
(libsource (lib "sallen_key_schlib") (part "Generic_Opamp") (description ""))
(property (name "Spice_Primitive") (value "X"))
(property (name "Spice_Model") (value "AD8051"))
(property (name "Spice_Lib_File") (value "ad8051.lib"))
(property (name "Spice_Netlist_Enabled") (value "Y"))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-00005788ff9f"))
(comp (ref "V1")
(value "AC 1")
(libsource (lib "sallen_key_schlib") (part "VSOURCE") (description ""))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-000057336052"))
(comp (ref "V2")
(value "DC 10")
(fields
(field (name "Fieldname") "Value")
(field (name "Spice_Node_Sequence") "1 2")
(field (name "Spice_Primitive") "V"))
(libsource (lib "sallen_key_schlib") (part "VSOURCE") (description ""))
(property (name "Fieldname") (value "Value"))
(property (name "Spice_Primitive") (value "V"))
(property (name "Spice_Node_Sequence") (value "1 2"))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-0000578900ba"))
(comp (ref "V3")
(value "DC 10")
(fields
(field (name "Fieldname") "Value")
(field (name "Spice_Node_Sequence") "1 2")
(field (name "Spice_Primitive") "V"))
(libsource (lib "sallen_key_schlib") (part "VSOURCE") (description ""))
(property (name "Fieldname") (value "Value"))
(property (name "Spice_Primitive") (value "V"))
(property (name "Spice_Node_Sequence") (value "1 2"))
(property (name "Sheetname") (value ""))
(property (name "Sheetfile") (value "sallen_key.kicad_sch"))
(sheetpath (names "/") (tstamps "/"))
(tstamps "00000000-0000-0000-0000-000057890232")))
(libparts
(libpart (lib "sallen_key_schlib") (part "C")
(footprints
(fp "C?")
(fp "C_????_*")
(fp "C_????")
(fp "SMD*_c")
(fp "Capacitor*"))
(fields
(field (name "Reference") "C")
(field (name "Value") "C"))
(pins
(pin (num "1") (name "") (type "passive"))
(pin (num "2") (name "") (type "passive"))))
(libpart (lib "sallen_key_schlib") (part "Generic_Opamp")
(fields
(field (name "Reference") "U")
(field (name "Value") "Generic_Opamp"))
(pins
(pin (num "1") (name "+") (type "input"))
(pin (num "2") (name "-") (type "input"))
(pin (num "3") (name "V+") (type "power_in"))
(pin (num "4") (name "V-") (type "power_in"))
(pin (num "5") (name "") (type "output"))))
(libpart (lib "sallen_key_schlib") (part "R")
(footprints
(fp "R_*")
(fp "Resistor_*"))
(fields
(field (name "Reference") "R")
(field (name "Value") "R"))
(pins
(pin (num "1") (name "") (type "passive"))
(pin (num "2") (name "") (type "passive"))))
(libpart (lib "sallen_key_schlib") (part "VSOURCE")
(fields
(field (name "Reference") "V")
(field (name "Value") "VSOURCE")
(field (name "Fieldname") "Value")
(field (name "Spice_Primitive") "V")
(field (name "Spice_Node_Sequence") "1 2"))
(pins
(pin (num "1") (name "") (type "input"))
(pin (num "2") (name "") (type "input")))))
(libraries
(library (logical "sallen_key_schlib")
(uri "/usr/share/kicad/demos/simulation/sallen_key/sallen_key_schlib.kicad_sym")))
(nets
(net (code "1") (name "/lowpass")
(node (ref "C1") (pin "1") (pintype "passive"))
(node (ref "U1") (pin "2") (pinfunction "-") (pintype "input"))
(node (ref "U1") (pin "5") (pintype "output")))
(net (code "2") (name "GND")
(node (ref "C2") (pin "2") (pintype "passive"))
(node (ref "V1") (pin "2") (pintype "input"))
(node (ref "V2") (pin "2") (pintype "input"))
(node (ref "V3") (pin "1") (pintype "input")))
(net (code "3") (name "Net-(C1-Pad2)")
(node (ref "C1") (pin "2") (pintype "passive"))
(node (ref "R1") (pin "1") (pintype "passive"))
(node (ref "R2") (pin "2") (pintype "passive")))
(net (code "4") (name "Net-(C2-Pad1)")
(node (ref "C2") (pin "1") (pintype "passive"))
(node (ref "R2") (pin "1") (pintype "passive"))
(node (ref "U1") (pin "1") (pinfunction "+") (pintype "input")))
(net (code "5") (name "Net-(R1-Pad2)")
(node (ref "R1") (pin "2") (pintype "passive"))
(node (ref "V1") (pin "1") (pintype "input")))
(net (code "6") (name "VDD")
(node (ref "U1") (pin "3") (pinfunction "V+") (pintype "power_in"))
(node (ref "V2") (pin "1") (pintype "input")))
(net (code "7") (name "VSS")
(node (ref "U1") (pin "4") (pinfunction "V-") (pintype "power_in"))
(node (ref "V3") (pin "2") (pintype "input")))))
In Spice format, the netlist is as follows:
.title KiCad schematic
.include "ad8051.lib"
XU1 Net-_C2-Pad1_ /lowpass VDD VSS /lowpass AD8051
C2 Net-_C2-Pad1_ GND 100n
C1 /lowpass Net-_C1-Pad2_ 100n
R2 Net-_C2-Pad1_ Net-_C1-Pad2_ 1k
R1 Net-_C1-Pad2_ Net-_R1-Pad2_ 1k
V1 Net-_R1-Pad2_ GND AC 1
V2 VDD GND DC 10
V3 GND VSS DC 10
.ac dec 10 1 1Meg
.end

---

## Understanding design variants

Every KiCad project starts with a single implicit variant called the default variant. The default
variant represents the base design with no overrides. When you create additional named
variants, each one begins as an exact copy of the default and can then be customized
independently.
Variant data is stored per symbol instance in the schematic. This means that the same symbol
used in different places in a hierarchical design can have different variant overrides at each
location. When you run Update PCB from Schematic, the variant data is transferred to the
corresponding footprints on the board.
The active variant is selected from a dropdown in the main toolbar of both the Schematic
Editor and the PCB Editor. Selecting a variant immediately updates the display to reflect that
variant’s overrides, including field text, DNP markings, and exclusion indicators.

---

## Editing variant data

When a non-default variant is selected in the toolbar, editing the schematic modifies that
variant rather than the base design. Edit variant data in bulk through the Symbol Fields Table,
or one symbol at a time with the normal schematic editing tools.
Editing fields in the Symbol Fields Table
The Symbol Fields Table is the primary tool for bulk-editing variant data. Select a variant from
the list on the left, then edit cell values directly in the grid. The grid shows the effective value for
each field in the selected variant.
Cells that differ from the default variant are highlighted with a colored background (yellow in
light themes, gold in dark themes). This makes it easy to review all overrides at a glance.
To set a field back to its default value, clear the cell or set it to match the default variant’s value.
The override is removed and the highlight disappears.
The same grid supports editing DNP and exclusion flags. The DNP, Exclude from BOM,
Exclude from Position Files, and Exclude from Simulation columns contain checkboxes that
can be toggled per variant.
Editing variants in the canvas
While a non-default variant is active, any edit made in the canvas updates that variant’s
overrides. The base design is unchanged. This applies to all the normal editing tools:
The Properties panel on the left shows the effective field values and attribute flags for the
active variant. Edits here update the variant’s overrides for the selected symbol.
The Symbol Properties dialog (double-click a symbol) shows the active variant name in its
title bar so you know edits apply to that variant.
In-place field edits on the canvas and attribute changes from the right-click menu also
apply to the active variant.
To mark a component as DNP for a specific variant, select the variant from the toolbar
dropdown, select the symbol, and check the Do not populate checkbox in the Properties
panel. The symbol is immediately drawn with an X overlay; switching back to the default variant
shows the symbol without the X (assuming it is fitted in the base design). The same procedure
works for the Exclude from BOM, Exclude from position files, and Exclude from simulation
checkboxes.
For bulk editing across many components at once, use the Symbol Fields Table.

---
