from django.urls import path
from rest_framework_simplejwt.views import  TokenRefreshView
from .views import MyTokenObtainPairView,UserRegisterationView,CreateGetJobPosition,ApplyForJob,JobApplicationView,SendEmailView,UserAppliedJobsAPIView,ExtractJobView,PromptTemplateListCreate,PromptTemplateDetail,SMTPConfigDetailAPIView,SMTPConfigListCreateAPIView,MyMailsAPIView
urlpatterns = [
    
    path('job/',CreateGetJobPosition.as_view()),  
    path('apply/<int:job_id>/',ApplyForJob.as_view()),
    path('job_application/<int:job_id>',JobApplicationView.as_view()),
    path('send_application/<int:appl_id>',SendEmailView.as_view()),
    path('user-applied-jobs/', UserAppliedJobsAPIView.as_view()),
    path('register/',UserRegisterationView.as_view()),  
    path('token/',MyTokenObtainPairView.as_view()),  
    path('refresh/', TokenRefreshView.as_view()),
    path("extract/", ExtractJobView.as_view(), name="extract-job"),
    path('prompts/', PromptTemplateListCreate.as_view(), name='prompt-list-create'),
    path('prompts/<int:pk>/', PromptTemplateDetail.as_view(), name='prompt-detail'),
    path("smtp-configs/", SMTPConfigListCreateAPIView.as_view(), name="smtp-config-list-create"),
    path("smtp-configs/<int:pk>/", SMTPConfigDetailAPIView.as_view(), name="smtp-config-detail"),
    path("applications/<int:appl_id>/send-email/", SendEmailView.as_view(), name="send-email"),
    path('mails/', MyMailsAPIView.as_view(), name='my-mails'),
]
