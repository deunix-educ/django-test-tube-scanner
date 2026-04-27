# planarian/forms.py

import csv
import io

from django import forms
from django.utils.translation import gettext_lazy as _
from .models import ExperimentConfig


class ExperimentConfigForm(forms.ModelForm):
    """Formulaire de saisie/modification d'un ExperimentConfig."""

    class Meta:
        model  = ExperimentConfig
        fields = "__all__"
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("thresh_immobile", 0) >= cleaned.get("thresh_mobile", 1):
            raise forms.ValidationError(
                _("Le seuil Immobile doit être inférieur au seuil Mobile.")
            )
        if cleaned.get("avoid_radius_mm", 0) >= cleaned.get("aggreg_radius_mm", 1):
            raise forms.ValidationError(
                _("Le rayon d'évitement doit être inférieur au rayon d'agrégation.")
            )
        return cleaned


class CsvImportForm(forms.Form):
    """Formulaire d'import de paramètres depuis un fichier CSV."""

    csv_file = forms.FileField(
        label=_("Fichier CSV"),
        help_text=_(
            "Colonnes obligatoires : experiment, well, px_per_mm, fps. "
            "Toutes les autres colonnes sont optionnelles."
        ),
    )
    overwrite = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Écraser les configurations existantes"),
    )

    def clean_csv_file(self):
        f = self.cleaned_data["csv_file"]
        try:
            content = f.read().decode("utf-8")
            reader  = csv.DictReader(io.StringIO(content))
            rows    = list(reader)
        except Exception as e:
            raise forms.ValidationError(_("Fichier CSV invalide : %(err)s") % {"err": e})

        required = {"experiment", "well", "px_per_mm", "fps"}
        if rows:
            missing = required - set(rows[0].keys())
            if missing:
                raise forms.ValidationError(
                    _("Colonnes manquantes : %(cols)s") % {"cols": ", ".join(missing)}
                )
        self.csv_rows = rows
        return f


class ExportCsvForm(forms.Form):
    """Formulaire de demande d'export CSV depuis ReductStore."""

    experiment  = forms.CharField(label=_("Expérience"), max_length=100)
    well        = forms.CharField(label=_("Puits"), max_length=20)
    planarian   = forms.IntegerField(label=_("Index planaire"), initial=0, min_value=0)
    record_type = forms.ChoiceField(
        label=_("Type d'enregistrement"),
        choices=[("frame", _("Frame par frame")), ("summary", _("Résumé"))],
        initial="frame",
    )
    start_dt = forms.DateTimeField(
        label=_("Début (UTC)"),
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    stop_dt = forms.DateTimeField(
        label=_("Fin (UTC)"),
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

