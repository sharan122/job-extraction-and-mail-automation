from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.core import signing

class User(AbstractUser):
    full_name = models.CharField(max_length=50)  
    bio = models.TextField()
    resume = models.FileField(upload_to="user/resumes/")
    linkedin_url = models.URLField()
    github_url = models.URLField()
    portfolio_url = models.URLField()
    email = models.EmailField()
    phone_number = models.CharField(max_length=10)
    def __str__(self):
        return self.full_name
 
class FundedCompany(models.Model):
    name = models.CharField(max_length=255)
    website = models.URLField()
    industry = models.CharField(max_length=255, blank=True, null=True)
    funding_round = models.CharField(max_length=100)
    funding_amount = models.DecimalField(max_digits=30, decimal_places=2, blank=True, null=True)
    investors = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name 
    
class JobListing(models.Model):
    company = models.ForeignKey(FundedCompany, on_delete=models.CASCADE, related_name="job_listings")
    title = models.CharField(max_length=500)
    job_description = models.TextField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    job_type = models.CharField(max_length=50, blank=True, null=True)  # Full-time, Part-time, etc.
    job_link = models.URLField(max_length=500)
    salary = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f'{self.title} at {self.company}'
    
class JobApplication(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    job = models.ForeignKey('JobListing', on_delete=models.CASCADE)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_applied = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.job.title}"
    
class PromptTemplate(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="prompts")
    name = models.CharField(max_length=100)  # e.g. “Short & Friendly”
    template = models.TextField()            # The actual prompt text with placeholders
    is_active = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'name')
        
        
class SMTPConfiguration(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="smtp_configs"
    )
    name = models.CharField(
        max_length=100,
        help_text="A friendly name, e.g. ‘Work Gmail’"
    )
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=587)
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)
    username = models.CharField(max_length=255)

    # store the signed/encrypted blob here, but call it “_raw_password”
    _raw_password = models.CharField(
        max_length=512,
        db_column="password",
        help_text="Encrypted via Django signing"
    )

    is_default = models.BooleanField(
        default=False,
        help_text="Used when no smtp_config_id is provided."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "name")

    def __str__(self):
        return f"{self.user.username}: {self.name}"

    @property
    def password(self) -> str:
        """
        Decrypts & returns the real SMTP password.
        """
        try:
            return signing.loads(self._raw_password)
        except signing.BadSignature:
            # data has been tampered with or corrupted
            return ""

    @password.setter
    def password(self, raw_password: str):
        """
        Signs (encrypts) and stores the password.
        """
        # Increase your salt/secret complexity by adding a custom salt here if you like
        self._raw_password = signing.dumps(raw_password)