from django import forms

class DelayedOrderUploadForm(forms.Form):
    file = forms.FileField(label="엑셀 파일 업로드")

class OptionStoreMappingUploadForm(forms.Form):
    file = forms.FileField(label="스토어명 매핑 엑셀 업로드", required=True)