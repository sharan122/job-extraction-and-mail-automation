from rest_framework import serializers
from .models import User,JobListing,JobApplication,PromptTemplate,SMTPConfiguration
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer



class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        token["username"] = user.username
        token["email"] = user.email
        return token
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(style={'input_type': 'password'},write_only=True,required=True)
    class Meta:
        model = User
        fields = ['id','username', 'phone_number','full_name', 'bio', 'resume', 'linkedin_url', 'github_url', 'portfolio_url', 'password','email']
        
    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        if not any(char.isupper() for char in value):
            raise serializers.ValidationError("Password must contain at least one uppercase letter.")
        if not any(char.isdigit() for char in value):
            raise serializers.ValidationError("Password must contain at least one number.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value
    
    
class JobPositionSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    is_applied = serializers.SerializerMethodField()

    class Meta:
        model = JobListing
        fields = [
            'id',
            'company_name',
            'title',
            'location',
            'job_type',
            'job_link',
            'salary',
            'created_at',
            'job_description',
            'is_applied',
        ]

    def get_is_applied(self, obj):
        user = self.context['request'].user
        return JobApplication.objects.filter(
            user=user,
            job=obj,
            is_applied=True
        ).exists()
        
    def validate(self, data):
        company = data.get('company')
        title = data.get('title')
        
        if JobListing.objects.filter(company=company, title=title).exists():
            raise serializers.ValidationError({'title': 'This title already exists for the given company.'})
        
        return data


class JobApplicationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source='job.company.name',
        read_only=True
    )

    class Meta:
        model = JobApplication
        fields = [
            'id',
            'user',
            'job',
            'subject',
            'body',
            'created_at',
            'updated_at',
            'is_applied',
            'company_name',   # ← include it here
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at', 'company_name']
        
class PromptTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptTemplate
        fields = ['id', 'name', 'template', 'is_active']
        read_only_fields = ['id']
        
class SMTPConfigurationSerializer(serializers.ModelSerializer):
    # explicitly override the EncryptedCharField fallback
    password = serializers.CharField(write_only=True)
    id       = serializers.IntegerField(read_only=True)

    class Meta:
        model = SMTPConfiguration
        fields = [
            "id", "name", "host", "port",
            "use_tls", "use_ssl",
            "username", "password",
            "is_default",
        ]
       
        read_only_fields = ("id",)

    def validate(self, attrs):
        # ensure only one default per user
        if attrs.get("is_default"):
            user = self.context["request"].user
            # clear any previous default
            SMTPConfiguration.objects.filter(user=user, is_default=True).update(is_default=False)
        return attrs