#
# encoding: utf-8
from django.shortcuts import render


def handler404(request, *args, **argv):
    return render(request, 'inc/404.html', status=404)


def handler500(request, *args, **argv):
    return render(request, 'inc/500.html', status=500)
