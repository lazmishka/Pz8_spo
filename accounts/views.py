from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Course


def home(request):
    """Public landing page for the site root."""
    return render(request, "home.html")


@login_required
def profile(request):
    course_count = Course.objects.count()
    return render(request, "profile.html", {
        "course_count": course_count,
        "course_progress": min(course_count * 10, 100),
    })


@login_required
def course_list(request):
    courses = Course.objects.select_related("department").all()
    return render(request, "course_list.html", {"courses": courses})
