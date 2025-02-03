# return_process/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, ReturnItem

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('email', 'name')


class ReturnItemForm(forms.ModelForm):
    class Meta:
        model = ReturnItem
        fields = ['processing_status', 'note', 'inspector', 'product_issue']
