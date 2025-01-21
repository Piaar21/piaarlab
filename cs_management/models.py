# cs_management/models.py
from django.db import models

class ChatRoom(models.Model):
    user_id = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    nickname = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.nickname or self.user_id
    
class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    text = models.TextField()
    image_url = models.URLField(blank=True, null=True)  # <-- 새로 추가 (이미지 경로)
    direction = models.CharField(
        max_length=10,
        choices=[('inbound','Inbound'),('outbound','Outbound')],
        default='inbound'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    seen = models.BooleanField(default=False)  # direction='inbound'인 메시지에서 주로 활용

    def __str__(self):
        return f"[{self.direction}] {self.text[:30]}"