"""A Rerun blueprint that plots one field of a signals struct as a line (ADR-0013 Compatibility): a time series view of the
entity, its SeriesLines fed by a component mapping that picks `.<field>` of the decoded message. Run with duck's Python
(it has rerun-sdk; the viewer's does not): python rerun_blueprint.py <application id> <out.rbl> <entity> <component> <field>"""

import sys

import rerun as rr
import rerun.blueprint as rrb
from rerun.blueprint.encodings import ComponentSourceKind, VisualizerComponentMapping

app, out, entity, component, field = sys.argv[1:6]
mapping = VisualizerComponentMapping(target="Scalars:scalars", source_kind=ComponentSourceKind.SourceComponent,
                                     source_component=component, selector=f".{field}")
line = rr.SeriesLines(names=field, colors=[(255, 0, 0)], widths=3.0)      # pure red: the test finds the line by its colour
rrb.Blueprint(rrb.TimeSeriesView(origin=entity, name=field, overrides={entity: line.visualizer(mappings=[mapping])}),
              collapse_panels=True).save(app, out)
