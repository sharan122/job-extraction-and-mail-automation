from django.shortcuts import render
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializer import MyTokenObtainPairSerializer,UserSerializer,JobPositionSerializer,JobApplicationSerializer,SMTPConfigurationSerializer
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny,IsAuthenticated
from .models import User,JobListing,JobApplication,FundedCompany
import google.generativeai as genai
from django.conf import settings
import json
from django.core.mail import EmailMessage, BadHeaderError
from smtplib import SMTPException
import traceback
from crawl4ai import AsyncWebCrawler
from crawl4ai import AsyncWebCrawler, BrowserConfig
import re
import asyncio
import logging
import openai
from rest_framework import  permissions
from .models import PromptTemplate
from .serializer import PromptTemplateSerializer
from django.shortcuts import get_object_or_404
from smtplib import SMTPException
from django.core.mail import BadHeaderError
from .models import JobApplication, SMTPConfiguration
from django.core.mail import EmailMessage, get_connection
browser_cfg = BrowserConfig(
    browser_type="chromium",
    headless=True,
)

# Create your views here.
class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer
    
class UserRegisterationView(APIView):
    permission_classes = [AllowAny]
    def post(self,request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            User.objects.create_user(
                **serializer.validated_data
            )
            return Response({"username":serializer.validated_data['username'],"email":serializer.validated_data['email']},status=status.HTTP_201_CREATED)
        print(serializer.errors,'error')
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
    

    
class CreateGetJobPosition(APIView):
    permission_classes = [IsAuthenticated]
    # def post(self,request):
    #     seriallizer = JobPositionSerializer(data=request.data)
    #     if seriallizer.is_valid():
    #         seriallizer.save()
    #         return Response({"messafe":'Job Positin Created '},status=status.HTTP_201_CREATED)
    #     return Response(seriallizer.errors,status=status.HTTP_400_BAD_REQUEST)
    def get(self, request):
        job_positions = JobListing.objects.all()
        serializer = JobPositionSerializer(
            job_positions,
            many=True,
            context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
    
to_logger = logging.getLogger(__name__)

class ApplyForJob(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, job_id=None):
        regenerate = request.query_params.get('regenerate') == 'true'
        job = get_object_or_404(JobListing, id=job_id)
        user = request.user

        # fetch any existing application
        existing = JobApplication.objects.filter(user=user, job=job).first()
        if existing and not regenerate:
            return Response(
                {"error": "You have already applied for this job."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # build prompt (unchanged)…
        try:
            prompt_obj = PromptTemplate.objects.get(user=user, is_active=True)
            user_instruction = prompt_obj.template
        except PromptTemplate.DoesNotExist:
            user_instruction = settings.DEFAULT_PROMPT
        data_block = f"""
        Job Title: {job.title}
        Company: {job.company}
        Description: {job.job_description}

        Applicant Information:
        Name: {user.full_name}
        Bio: {user.bio}
        Email: {user.email}
        Phone: {user.phone_number}
        LinkedIn: {user.linkedin_url}
        GitHub: {user.github_url}
        Portfolio: {user.portfolio_url}

        Return the result in JSON format:
        {{"subject": "The email subject line", "body": "The complete email body"}}
        """
        prompt_text = f"{user_instruction}\n\n{data_block}"

        # call OpenAI
        openai.api_key = settings.OPENAI_API_KEY
        try:
            client = openai.OpenAI()
            resp = client.chat.completions.create(
                model="gpt-4o-mini-2024-07-18",
                messages=[{"role":"user","content":prompt_text}],
                temperature=0.4
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n",1)[1].rsplit("```",1)[0].strip()
            data = json.loads(raw)
            subject, body = data["subject"].strip(), data["body"].strip()

            # create or update
            if existing and regenerate:
                existing.subject = subject
                existing.body = body
                existing.save()
                application = existing
            else:
                application = JobApplication.objects.create(
                    user=user, job=job,
                    subject=subject, body=body,
                    is_applied=False
                )

            return Response({
                "message": "Application generated",
                "data": JobApplicationSerializer(application).data
            }, status=status.HTTP_201_CREATED)

        except json.JSONDecodeError as e:
            logger.error("JSON parse error", exc_info=True)
            return Response(
                {"error": f"Failed to parse JSON: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error("Unexpected error", exc_info=True)
            return Response(
                {"error": f"Something went wrong: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
     
class JobApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id=None):
        
        applications = JobApplication.objects.filter(user=request.user)
        if job_id:
            applications = applications.filter(job__id=job_id)
            if not applications:
                return Response({"error": "No application found for this job"}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = JobApplicationSerializer(applications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    def put(self, request, job_id):
        try:
            application = JobApplication.objects.get(user=request.user, job__id=job_id)
        except JobApplication.DoesNotExist:
            return Response({"error": "Application not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = JobApplicationSerializer(application, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
           
            return Response({"message": "Application updated ", "data": serializer.data}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
class SendEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, appl_id):
        # 1. Fetch job application
        try:
            application = JobApplication.objects.get(user=request.user, id=appl_id)
        except JobApplication.DoesNotExist:
            return Response({"error": "Application not found"},
                            status=status.HTTP_404_NOT_FOUND)

        # 2. Receiver and optional smtp_config_id from front end
        receiver_email = request.data.get("receiver_email")
        smtp_config_id = request.data.get("smtp_config_id")
        if not receiver_email:
            return Response({"error": "Receiver email is required"},
                            status=status.HTTP_400_BAD_REQUEST)

        # 3. Load resume
        user_resume = application.user.resume
        if not getattr(user_resume, "path", None):
            return Response({"error": "Resume file not found"},
                            status=status.HTTP_400_BAD_REQUEST)

        # 4. Get SMTP config (fallback to settings if none in DB)
        try:
            if smtp_config_id:
                config = SMTPConfiguration.objects.get(user=request.user, id=smtp_config_id)
            else:
                config = SMTPConfiguration.objects.get(user=request.user, is_default=True)

            host = config.host
            port = config.port
            username = config.username
            password = config.password
            use_tls = config.use_tls
            use_ssl = config.use_ssl
        except SMTPConfiguration.DoesNotExist:
            host = settings.EMAIL_HOST
            port = settings.EMAIL_PORT
            username = settings.EMAIL_HOST_USER
            password = settings.EMAIL_HOST_PASSWORD
            use_tls = getattr(settings, 'EMAIL_USE_TLS', False)
            use_ssl = getattr(settings, 'EMAIL_USE_SSL', False)

        # 5. Build a custom connection
        connection = get_connection(
            backend=getattr(settings, 'EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend'),
            host=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
            use_ssl=use_ssl,
        )

        # 6. Compose & send
        try:
            mail = EmailMessage(
                subject=application.subject,
                body=application.body,
                from_email=username,
                to=[receiver_email],
                connection=connection,
            )
            with open(user_resume.path, "rb") as f:
                mail.attach(user_resume.name, f.read(), "application/pdf")

            mail.send()

            # Mark application as applied
            application.is_applied = True
            application.save()

            return Response(
                {"message": "Application has been sent to the employer"},
                status=status.HTTP_200_OK
            )

        except BadHeaderError:
            return Response(
                {"error": "Invalid header found in the email"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except SMTPException as e:
            return Response(
                {"error": f"SMTP error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            return Response(
                {"error": f"Unexpected error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    
class UserAppliedJobsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Fetch only applications marked as applied
        applications = JobApplication.objects.filter(
            user=request.user,
            is_applied=True
        )
        # Serialize the related job listings
        jobs = [app.job for app in applications]
        serializer = JobPositionSerializer(
            jobs,
            many=True,
            context={'request': request}
        )
        return Response({
            "applied_jobs": serializer.data
        }, status=status.HTTP_200_OK)

    
    
logger = logging.getLogger(__name__)

class ExtractJobView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        url = request.data.get("url")
        logger.debug(f"[POST] /api/extract/ called by {request.user} with payload: {request.data!r}")

        if not url:
            logger.warning("No URL provided in request")
            return Response({"error": "No URL provided."}, status=status.HTTP_400_BAD_REQUEST)

        # 1) Crawl the page
        try:
            logger.debug(f"Starting crawl for URL: {url}")
            crawl_result = asyncio.run(self._crawl_page(url))
            logger.debug(f"Crawl completed: {crawl_result!r}")
        except Exception as e:
            logger.exception("Failed to crawl URL")
            return Response(
                {"error": "Failed to crawl URL", "detail": str(e), "traceback": traceback.format_exc()},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        page_text = getattr(crawl_result, "markdown", None)
        if not page_text:
            logger.error("Crawler returned no usable content")
            return Response({"error": "Crawler returned no usable content."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.debug(f"Extracted page_text (first 200 chars): {page_text[:200]!r}")

        # 2) Ask Gemini to extract JSON
        genai.configure(api_key=settings.GEN_AI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""
        You are given the full text of a single job posting in the variable `page_text`.
        Your job is to extract these six fields:

        • title
        • company
        • location
        • job_type
        • salary
        • job_description

        Return only a single JSON object with exactly these keys (no extra keys, no prose, no markdown):
        ```json
        {{
        "title": string | null,
        "company": string | null,
        "location": string | null,
        "job_type": string | null,
        "salary": string | null,
        "job_description": string | null
        }}
        ```
        If a field is not present, set its value to null.

        Here is the job posting text:
        {page_text}"""
        logger.debug("Prompt sent to Gemini (truncated): %s", prompt[:300])

        raw = ""
        try:
            response = model.generate_content(prompt)
            raw = response.text.strip()
            logger.debug("Raw model output: %s", raw)

            # Strip markdown fences if present
            cleaned = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()
            logger.debug("Cleaned JSON string: %s", cleaned)

            data = json.loads(cleaned)
            logger.debug("Parsed JSON data: %s", data)
        except json.JSONDecodeError as e:
            logger.error("JSON parsing failed: %s", e)
            return Response(
                {"error": "Failed to parse JSON from model", "detail": str(e), "raw_model_output": raw},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.exception("Model generation error")
            return Response(
                {"error": "Model generation error", "detail": str(e), "traceback": traceback.format_exc()},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 3) Ensure company exists in FundedCompany
        try:
            company_name = (data.get("company") or "").strip()
            company_obj = None
            if company_name:
                company_obj, created = FundedCompany.objects.get_or_create(name=company_name)
                logger.debug("Company '%s' %s", company_name, "created" if created else "found")
        except Exception as e:
            logger.exception("Failed to get or create FundedCompany")
            return Response(
                {"error": "Company save error", "detail": str(e), "traceback": traceback.format_exc()},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 4) Persist JobListing via Django ORM
        try:
            job = JobListing.objects.create(
                job_link=url,
                title=(data.get("title") or "").strip(),
                company=company_obj,
                location=(data.get("location") or "Not Specified").strip(),
                job_type=(data.get("job_type") or "Not Specified").strip(),
                salary=(data.get("salary") or "Not Specified").strip(),
                job_description=(data.get("job_description") or "").strip(),
                created_at=request.user
            )
            logger.debug("Created JobListing id=%s", job.id)
        except Exception as e:
            logger.exception("Failed to save JobListing to DB")
            return Response(
                {"error": "Database error", "detail": str(e), "traceback": traceback.format_exc()},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 5) Return the saved record
        return Response(
            {"id": job.id, "title": job.title, "company": job.company.name if job.company else None, "job_description": job.job_description},
            status=status.HTTP_201_CREATED
        )

    @staticmethod
    async def _crawl_page(url):
        crawler = AsyncWebCrawler(config=browser_cfg)
        try:
            await crawler.start()
            return await crawler.arun(url)
        finally:
            await crawler.close()



class PromptTemplateListCreate(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        prompts = PromptTemplate.objects.filter(user=request.user)
        serializer = PromptTemplateSerializer(prompts, many=True)
        return Response(serializer.data)

    def post(self, request):
        # If they want to activate this one, deactivate others
        if request.data.get('is_active'):
            PromptTemplate.objects.filter(user=request.user, is_active=True).update(is_active=False)

        serializer = PromptTemplateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PromptTemplateDetail(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, pk, user):
        return get_object_or_404(PromptTemplate, pk=pk, user=user)

    def get(self, request, pk):
        prompt = self.get_object(pk, request.user)
        serializer = PromptTemplateSerializer(prompt)
        return Response(serializer.data)

    def patch(self, request, pk):
        prompt = self.get_object(pk, request.user)

        # If toggling to active, turn off others
        if request.data.get('is_active'):
            PromptTemplate.objects.filter(user=request.user, is_active=True).exclude(pk=pk).update(is_active=False)

        serializer = PromptTemplateSerializer(prompt, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        prompt = self.get_object(pk, request.user)
        prompt.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    
    
class SMTPConfigListCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        configs = SMTPConfiguration.objects.filter(user=request.user)
        serializer = SMTPConfigurationSerializer(configs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = SMTPConfigurationSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SMTPConfigDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, pk, user):
        try:
            return SMTPConfiguration.objects.get(pk=pk, user=user)
        except SMTPConfiguration.DoesNotExist:
            return None

    def get(self, request, pk):
        config = self.get_object(pk, request.user)
        if not config:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = SMTPConfigurationSerializer(config)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        config = self.get_object(pk, request.user)
        if not config:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = SMTPConfigurationSerializer(
            config, data=request.data, partial=False, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        config = self.get_object(pk, request.user)
        if not config:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = SMTPConfigurationSerializer(
            config, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        config = self.get_object(pk, request.user)
        if not config:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        config.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    

class MyMailsAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, format=None):
        user = request.user

        try:
            queryset = (
                JobApplication.objects
                .filter(user=user)
                .select_related('job__company')              # ← pull in the JobListing → FundedCompany
                .order_by('-created_at')
            )
            serializer = JobApplicationSerializer(queryset, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as exc:
            logger.exception(f"Error fetching mails for user {user.pk}: {exc}")
            return Response(
                {'detail': 'An internal error occurred while retrieving mails.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )