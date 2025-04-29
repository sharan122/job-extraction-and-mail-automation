from django.contrib import admin
from .models import User,JobListing,JobApplication
# Register your models here.
admin.site.register(JobApplication)
admin.site.register(User)
admin.site.register(JobListing)