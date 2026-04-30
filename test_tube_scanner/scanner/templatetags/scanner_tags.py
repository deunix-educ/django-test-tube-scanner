# encoding: utf-8
from django import template
from django.utils.html import mark_safe

register = template.Library()

@register.simple_tag
def multiwell_cards(sid, experiment):
    multiwells = []
    row_def = experiment.multiwell.row_def.split(',')
    multiwells.append(
    f'''
    <div class="w3-center w3-sand">{experiment.title}</div>
    <div class="w3-border multiwell_cards">
    ''')
    for row in range(experiment.multiwell.rows):
        for col in range(experiment.multiwell.cols):
            btn = f'{row_def[row]}{col+1}'
            uuid = f'{sid}-{experiment.multiwell.position}-{btn}'
            multiwells.append(f"""<button id="btn-{uuid}" name="_multiwell" class="multiwell w3-button" value="{uuid}" onclick="this.form.submit()">{btn}</button>""")
    multiwells.append('''</div>''')

    return mark_safe("\n".join(multiwells))
