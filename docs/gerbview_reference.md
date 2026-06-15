# KiCad GerbView Agent Reference

**Distilled from:** KiCad 10.99 GerbView Reference Manual

GerbView is a lightweight viewer for Gerber files, drill files, and board fabrication outputsAgents primarily interact with it through `kicad-cli` CLI commands---

Table of Contents

.to

.2.2.window

.2.3.4Manager

.5.in

.bar

.5.6.6.7KiCad Nightly Reference Manual

This document is Copyright The KiCad Documentation ContributorsYou may distribute it and/or modify it

under the terms of either the GNU General Public License (https://www.gnu.org/licenses/gpl.html), version 3

or later, or the Creative Commons Attribution License (https://creativecommons.org/licenses/by/3.0/),

version 3.0 or laterAll trademarks within this guide belong to their legitimate ownersThe KiCad project welcomes feedback, bug reports, and suggestions related to the software or its

documentationFor more information on how to submit feedback or report an issue, please see the

instructions at https://www.kicad.org/help/report-an-issue/

Software and Documentation Version

This user manual is based on KiCad 10.99Functionality and appearance may be different in other versions

Documentation revision: 2e473680 Introduction to GerbView

GerbView is a Gerber file (RS-274X format) and Excellon drill file viewerUp to 32 files can be displayed at

For more information about the Gerber file format please read the Gerber File Format SpecificationDetails

about drill file format can be found at the Excellon format descriptionClear all layers

Load Gerber files

Load Excellon drill files

Zoom to fit page

Zoom to selection

Select active layer

Display info about active layer

Highlight items belonging to selected component (Gerber

Highlight items belonging to selected net (Gerber X2)

Highlight items with the selected attribute (Gerber X2)

Highlight items of selected D Code on the active layer

Measure between two points

Toggle grid visibility

Toggle polar coordinates display

Select inch, mils, or millimeter units

Toggle full-screen cursor

Display flashed items in sketch (outline) mode

Display lines in sketch (outline) mode

Display polygons in sketch (outline) mode

Show negative objects in ghost color

Show/hide D Codes

Display layers in diff (compare) mode

Toggle inactive layers between normal and dimmed display

Show/hide layer manager

Show Gerbers as mirror image

The Layers Manager controls and displays visibility of all layersAn arrow indicates the active layer, and

each layer can be shown or hidden with the checkboxesMouse button assignments:

Left click: select the active layer

Right click: show/hide/sort layers options

Middle click or double click (on color swatch): select the layer color

The Layers tab allows you to control the visibility and color of all loaded Gerber and drill layersThe Items

tab allows you to control the color and display of the grid, D Codes, and negative objectsCommands in menu bar

Export to PCB Editor is a limited capability to export Gerber files into a KiCad PCBThe final result

depends on what features of the RS-274X format are used in the original Gerber files: rasterized items

cannot be converted (typically negative objects), flashed items are converted to vias, lines are converted

to track segments (or graphic lines for non-copper layers)List DCodes shows the D Code information for all layersShow Source displays the Gerber file contents of the active layer in a text editorMeasure Tool allows measuring the distance between two pointsClear Current Layer erases the contents of the active layerTo print layers, use the

icon or the File → Print menuBe sure items are inside the printable areaUse

to select a suitable page formatNote that many photoplotters support a large plottable area, much bigger than the page

sizes used by most printersMoving the entire layer set may be required
