# encoding: utf-8
from django import template
from django.utils.html import mark_safe

register = template.Library()

@register.simple_tag
def multiwell_cards(sid, observations):
    multiwells = []
    for obs in observations:
        row_def = obs.multiwell.row_def.split(',')
        multiwells.append(
        f'''
        <div class="w3-center w3-sand">{obs.title}</div>
        <div class="w3-border multiwell_cards">
        ''')
        for row in range(obs.multiwell.rows):
            for col in range(obs.multiwell.cols):
                btn = f'{row_def[row]}{col+1}'
                uuid = f'{sid}-{obs.multiwell.position}-{btn}'
                multiwells.append(f"""<button id="btn-{uuid}" name="_multiwell" class="multiwell w3-button" value="{uuid}" onclick="this.form.submit()">{btn}</button>""")
        multiwells.append('''</div>''')

    return mark_safe("\n".join(multiwells))

 
