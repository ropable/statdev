from __future__ import unicode_literals
from datetime import date
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse, HttpResponseRedirect
from django.views.generic import TemplateView, ListView, DetailView, CreateView, UpdateView
from extra_views import ModelFormSetView
import pdfkit

from accounts.utils import get_query
from actions.models import Action
from applications import forms as apps_forms
from django.core.exceptions import ObjectDoesNotExist
from .models import Application, Referral, Condition, Compliance, Vessel, Location, Document


class HomePage(LoginRequiredMixin, TemplateView):
    # TODO: rename this view to something like UserDashboard.
    template_name = 'applications/home_page.html'

    def get_context_data(self, **kwargs):
        context = super(HomePage, self).get_context_data(**kwargs)
        if Application.objects.filter(assignee=self.request.user).exclude(state__in=[Application.APP_STATE_CHOICES.issued, Application.APP_STATE_CHOICES.declined]).exists():
            context['applications_wip'] = Application.objects.filter(
                assignee=self.request.user).exclude(state__in=[Application.APP_STATE_CHOICES.issued, Application.APP_STATE_CHOICES.declined])
        if Application.objects.filter(applicant=self.request.user).exists():
            context['applications_submitted'] = Application.objects.filter(
                applicant=self.request.user).exclude(assignee=self.request.user)
        if Referral.objects.filter(referee=self.request.user).exists():
            context['referrals'] = Referral.objects.filter(
                referee=self.request.user, status=Referral.REFERRAL_STATUS_CHOICES.referred)
        # TODO: any restrictions on who can create new applications?
        context['may_create'] = True
        # Processor users only: show unassigned applications.
        processor = Group.objects.get(name='Processor')
        if processor in self.request.user.groups.all() or self.request.user.is_superuser:
            if Application.objects.filter(assignee__isnull=True, state=Application.APP_STATE_CHOICES.with_admin).exists():
                context['applications_unassigned'] = Application.objects.filter(
                    assignee__isnull=True, state=Application.APP_STATE_CHOICES.with_admin)
            # Rule: admin officers may self-assign applications.
            context['may_assign_processor'] = True
        return context


class ApplicationList(ListView):
    model = Application

    def get_queryset(self):
        qs = super(ApplicationList, self).get_queryset()
        # Did we pass in a search string? If so, filter the queryset and return it.
        if 'q' in self.request.GET and self.request.GET['q']:
            query_str = self.request.GET['q']
            # Replace single-quotes with double-quotes
            query_str = query_str.replace("'", r'"')
            # Filter by pk, title, applicant__email, organisation__name,
            # assignee__email
            query = get_query(
                query_str, ['pk', 'title', 'applicant__email', 'organisation__name', 'assignee__email'])
            qs = qs.filter(query).distinct()
        return qs

    def get_context_data(self, **kwargs):
        context = super(ApplicationList, self).get_context_data(**kwargs)
        # TODO: any restrictions on who can create new applications?
        context['may_create'] = True
        processor = Group.objects.get(name='Processor')
        # Rule: admin officers may self-assign applications.
        if processor in self.request.user.groups.all() or self.request.user.is_superuser:
            context['may_assign_processor'] = True
        return context


class ApplicationCreate(LoginRequiredMixin, CreateView):
    form_class = apps_forms.ApplicationCreateForm
    template_name = 'applications/application_form.html'

    def get_context_data(self, **kwargs):
        context = super(ApplicationCreate, self).get_context_data(**kwargs)
        context['page_heading'] = 'Create new application'
        return context

    def get_form_kwargs(self):
        kwargs = super(ApplicationCreate, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(reverse('home_page'))
        return super(ApplicationCreate, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        """Override form_valid to set the assignee as the object creator.
        """
        self.object = form.save(commit=False)
        # If this is not an Emergency Works set the applicant as current user
        if not (self.object.app_type == Application.APP_TYPE_CHOICES.emergency):
            self.object.applicant = self.request.user
        self.object.assignee = self.request.user
        self.object.submitted_by = self.request.user
        self.object.submit_date = date.today()
        self.object.state = self.object.APP_STATE_CHOICES.new
        self.object.save()
        success_url = reverse('application_update', args=(self.object.pk,))
        return HttpResponseRedirect(success_url)


class ApplicationDetail(DetailView):
    model = Application

    def get_context_data(self, **kwargs):
        context = super(ApplicationDetail, self).get_context_data(**kwargs)
        app = self.get_object()

        if app.app_type == app.APP_TYPE_CHOICES.part5:
            self.template_name = 'applications/application_details_part5_new_application.html'
            LocObj = Location.objects.get(application_id=self.object.id)
            context['certificate_of_title_volume'] = LocObj.title_volume
            context['folio'] = LocObj.folio
            context['diagram_plan_deposit_number'] = LocObj.dpd_number
            context['location'] = LocObj.location
            context['reserve_number'] = LocObj.reserve
            context['street_number_and_name'] = LocObj.street_number_name
            context['town_suburb'] = LocObj.suburb
            context['lot'] = LocObj.lot
            context['nearest_road_intersection'] = LocObj.intersection
        elif app.app_type == app.APP_TYPE_CHOICES.emergency:
            self.template_name = 'applications/application_detail_emergency.html'

        processor = Group.objects.get(name='Processor')
        assessor = Group.objects.get(name='Assessor')
        approver = Group.objects.get(name='Approver')
        referee = Group.objects.get(name='Referee')
        if app.state in [app.APP_STATE_CHOICES.new, app.APP_STATE_CHOICES.draft]:
            # Rule: if the application status is 'draft', it can be updated.
            # Rule: if the application status is 'draft', it can be lodged.
            if app.applicant == self.request.user or self.request.user.is_superuser:
                context['may_update'] = True
                context['may_lodge'] = True
        if processor in self.request.user.groups.all() or self.request.user.is_superuser:
            # Rule: if the application status is 'with admin', it can be sent
            # back to the customer.
            if app.state == app.APP_STATE_CHOICES.with_admin:
                context['may_assign_customer'] = True
            # Rule: if the application status is 'with admin' or 'with referee', it can
            # be referred, have conditions added, and referrals can be
            # recalled/resent.
            if app.state in [app.APP_STATE_CHOICES.with_admin, app.APP_STATE_CHOICES.with_referee]:
                context['may_refer'] = True
                context['may_create_condition'] = True
                context['may_recall_resend'] = True
                context['may_assign_processor'] = True
                # Rule: if there are no "outstanding" referrals, it can be
                # assigned to an assessor.
                if not Referral.objects.filter(application=app, status=Referral.REFERRAL_STATUS_CHOICES.referred).exists():
                    context['may_assign_assessor'] = True
        if assessor in self.request.user.groups.all() or self.request.user.is_superuser:
            # Rule: if the application status is 'with assessor', it can have conditions added
            # or updated, and can be sent for approval.
            if app.state == app.APP_STATE_CHOICES.with_assessor:
                context['may_create_condition'] = True
                context['may_update_condition'] = True
                context['may_submit_approval'] = True
        if approver in self.request.user.groups.all() or self.request.user.is_superuser:
            # Rule: if the application status is 'with manager', it can be issued or
            # assigned back to an assessor.
            if app.state == app.APP_STATE_CHOICES.with_manager:
                context['may_assign_assessor'] = True
                context['may_issue'] = True
        if referee in self.request.user.groups.all():
            # Rule: if the application has a current referral to the request
            # user, they can create conditions.
            if Referral.objects.filter(application=app, status=Referral.REFERRAL_STATUS_CHOICES.referred).exists():
                context['may_create_condition'] = True
        if app.state == app.APP_STATE_CHOICES.issued:
            context['may_generate_pdf'] = True
        if app.state == app.APP_STATE_CHOICES.issued and app.condition_set.exists():
            # Rule: only the delegate of the organisation (or submitter) can
            # request compliance.
            if app.organisation:
                if self.request.user.emailprofile in app.organisation.delegates.all():
                    context['may_request_compliance'] = True
            elif self.request.user == app.applicant:
                context['may_request_compliance'] = True
        return context


class ApplicationDetailPDF(ApplicationDetail):
    """This view is a proof of concept for synchronous, server-side PDF generation.
    Depending on performance and resource constraints, this might need to be
    refactored to use an asynchronous task.
    """
    template_name = 'applications/application_detail_pdf.html'

    def get(self, request, *args, **kwargs):
        response = super(ApplicationDetailPDF, self).get(request)
        options = {
            'page-size': 'A4',
            'encoding': 'UTF-8',
        }
        # Generate the PDF as a string, then use that as the response body.
        output = pdfkit.from_string(
            response.rendered_content, False, options=options)
        # TODO: store the generated PDF as a Document object.
        response = HttpResponse(output, content_type='application/pdf')
        obj = self.get_object()
        response['Content-Disposition'] = 'attachment; filename=application_{}.pdf'.format(
            obj.pk)
        return response


class ApplicationActions(DetailView):
    model = Application
    template_name = 'applications/application_actions.html'

    def get_context_data(self, **kwargs):
        context = super(ApplicationActions, self).get_context_data(**kwargs)
        app = self.get_object()
        # TODO: define a GenericRelation field on the Application model.
        context['actions'] = Action.objects.filter(
            content_type=ContentType.objects.get_for_model(app), object_id=app.pk).order_by('-timestamp')
        return context


class ApplicationUpdate(LoginRequiredMixin, UpdateView):
    """A view for updating a draft (non-lodged) application.
    """
    model = Application

    def get(self, request, *args, **kwargs):
        # TODO: business logic to check the application may be changed.
        app = self.get_object()
        # Rule: if the application status is 'draft', it can be updated.
        if app.state != app.APP_STATE_CHOICES.draft and app.state != app.APP_STATE_CHOICES.new:
            messages.error(self.request, 'This application cannot be updated!')
            return HttpResponseRedirect(app.get_absolute_url())
        return super(ApplicationUpdate, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(ApplicationUpdate, self).get_context_data(**kwargs)
        context['page_heading'] = 'Update application details'
        return context

    def get_form_class(self):
        if self.object.app_type == self.object.APP_TYPE_CHOICES.licence:
            return apps_forms.ApplicationLicencePermitForm
        elif self.object.app_type == self.object.APP_TYPE_CHOICES.permit:
            return apps_forms.ApplicationPermitForm
        elif self.object.app_type == self.object.APP_TYPE_CHOICES.part5:
            return apps_forms.ApplicationPart5Form
        elif self.object.app_type == self.object.APP_TYPE_CHOICES.emergency:
            return apps_forms.ApplicationEmergencyForm

    def get_initial(self):
        initial = super(ApplicationUpdate, self).get_initial()
        app = self.get_object()
        if app.document_draft:
            initial['document_draft'] = app.document_draft.upload
#        if app.proposed_development_plans:
#           initial['proposed_development_plans'] = app.proposed_development_plans.upload
        if app.document_final:
            initial['document_final'] = app.document_final.upload
        if app.document_determination:
            initial['document_determination'] = app.document_determination.upload
        if app.document_completion:
            initial['document_completion'] = app.document_completion.upload
        # Document FK fields:
        if app.cert_survey:
            initial['cert_survey'] = app.cert_survey.upload
        if app.cert_public_liability_insurance:
            initial['cert_public_liability_insurance'] = app.cert_public_liability_insurance.upload
        if app.risk_mgmt_plan:
            initial['risk_mgmt_plan'] = app.risk_mgmt_plan.upload
        if app.safety_mgmt_procedures:
            initial['safety_mgmt_procedures'] = app.safety_mgmt_procedures.upload
        if app.deed:
            initial['deed'] = app.deed.upload

        try:
            LocObj = Location.objects.get(application_id=self.object.id)
            initial['certificate_of_title_volume'] = LocObj.title_volume
            initial['folio'] = LocObj.folio
            initial['diagram_plan_deposit_number'] = LocObj.dpd_number
            initial['location'] = LocObj.location
            initial['reserve_number'] = LocObj.reserve
            initial['street_number_and_name'] = LocObj.street_number_name
            initial['town_suburb'] = LocObj.suburb
            initial['lot'] = LocObj.lot
            initial['nearest_road_intersection'] = LocObj.intersection
        except ObjectDoesNotExist:
            donothing = ''

        return initial

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            app = Application.objects.get(id=kwargs['pk'])
            if app.state == app.APP_STATE_CHOICES.new:
                app.delete()
                return HttpResponseRedirect(reverse('application_list'))
            return HttpResponseRedirect(self.get_object().get_absolute_url())
        return super(ApplicationUpdate, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        """Override form_valid to set the state to draft is this is a new application.
        """
        forms_data = form.cleaned_data
        self.object = form.save(commit=False)

        try:
            new_loc = Location.objects.get(application_id=self.object.id)
        except:
            new_loc = Location()
            new_loc.application_id = self.object.id

        # TODO: Potentially refactor to separate process_documents method
        # Document upload fields.
        if 'cert_survey-clear' in form.data and self.object.cert_survey:  # 'Clear' was checked.
            self.object.cert_survey = None
        if self.request.FILES.get('cert_survey'):  # Uploaded new file.
            if self.object.cert_survey:
                doc = self.object.cert_survey
            else:
                doc = Document()
            doc.upload = forms_data['cert_survey']
            doc.name = forms_data['cert_survey'].name
            doc.save()
            self.object.cert_survey = doc
        if 'cert_public_liability_insurance-clear' in form.data and self.object.cert_public_liability_insurance:
            self.object.cert_public_liability_insurance = None
        if self.request.FILES.get('cert_public_liability_insurance'):
            if self.object.cert_public_liability_insurance:
                doc = self.object.cert_public_liability_insurance
            else:
                doc = Document()
            doc.upload = forms_data['cert_public_liability_insurance']
            doc.name = forms_data['cert_public_liability_insurance'].name
            doc.save()
            self.object.cert_public_liability_insurance = doc
        if 'risk_mgmt_plan-clear' in form.data and self.object.risk_mgmt_plan:
            self.object.risk_mgmt_plan = None
        if self.request.FILES.get('risk_mgmt_plan'):
            if self.object.risk_mgmt_plan:
                doc = self.object.risk_mgmt_plan
            else:
                doc = Document()
            doc.upload = forms_data['risk_mgmt_plan']
            doc.name = forms_data['risk_mgmt_plan'].name
            doc.save()
            self.object.risk_mgmt_plan = doc
        if 'safety_mgmt_procedures-clear' in form.data and self.object.safety_mgmt_procedures:
            self.object.safety_mgmt_procedures = None
        if self.request.FILES.get('safety_mgmt_procedures'):
            if self.object.safety_mgmt_procedures:
                doc = self.object.safety_mgmt_procedures
            else:
                doc = Document()
            doc.upload = forms_data['safety_mgmt_procedures']
            doc.name = forms_data['safety_mgmt_procedures'].name
            doc.save()
            self.object.safety_mgmt_procedures = doc
        if 'deed-clear' in form.data and self.object.deed:
            self.object.deed = None
        if self.request.FILES.get('deed'):
            if self.object.deed:
                doc = self.object.deed
            else:
                doc = Document()
            doc.upload = forms_data['deed']
            doc.name = forms_data['deed'].name
            doc.save()
            self.object.deed = doc
        if self.request.FILES.get('brochures_itineries_adverts'):
            # Remove existing documents.
            for d in self.object.brochures_itineries_adverts.all():
                self.object.brochures_itineries_adverts.remove(d)
            # Add new uploads.
            for f in forms_data['brochures_itineries_adverts']:
                doc = Document()
                doc.upload = f
                doc.name = f.name
                doc.save()
                self.object.brochures_itineries_adverts.add(doc)
        if self.request.FILES.get('land_owner_consent'):
            # remove existing documents.
            for d in self.object.land_owner_consent.all():
                self.object.land_owner_consent.remove(d)
            # add new uploads.
            for f in forms_data['land_owner_consent']:
                doc = Document()
                doc.upload = f
                doc.name = f.name
                doc.save()
                self.object.land_owner_consent.add(doc)

        if self.request.POST.get('document_draft-clear'):
            application = Application.objects.get(id=self.object.id)
            document = Document.objects.get(pk=application.document_draft.id)
            document.delete()
            self.object.document_draft = None

        if self.request.FILES.get('document_draft'):
            new_doc = Document()
            new_doc.upload = self.request.FILES['document_draft']
            new_doc.save()
            self.object.document_draft = new_doc

        if self.request.FILES.get('document_final'):
            new_doc = Document()
            new_doc.upload = self.request.FILES['document_final']
            new_doc.save()
            self.object.document_final = new_doc

        if self.request.FILES.get('document_determination'):
            new_doc = Document()
            new_doc.upload = self.request.FILES['document_determination']
            new_doc.save()
            self.object.document_determination = new_doc

        if self.request.FILES.get('document_completion'):
            new_doc = Document()
            new_doc.upload = self.request.FILES['document_completion']
            new_doc.save()
            self.object.document_completion = new_doc

        #new_loc.title_volume = forms_data['certificate_of_title_volume']
        if 'certificate_of_title_volume' in forms_data:
            new_loc.title_volume = forms_data['certificate_of_title_volume']
        if 'folio' in forms_data:
            new_loc.folio = forms_data['folio']
        if 'diagram_plan_deposit_number' in forms_data:
            new_loc.dpd_number = forms_data['diagram_plan_deposit_number']
        if 'location' in forms_data:
            new_loc.location = forms_data['location']
        if 'reserve_number' in forms_data:
            new_loc.reserve = forms_data['reserve_number']
        if 'street_number_and_name' in forms_data:
            new_loc.street_number_name = forms_data['street_number_and_name']
        if 'town_suburb' in forms_data:
            new_loc.suburb = forms_data['town_suburb']
        if 'lot' in forms_data:
            new_loc.lot = forms_data['lot']
        if 'lot' in forms_data:
            new_loc.intersection = forms_data['nearest_road_intersection']

        if self.object.state == Application.APP_STATE_CHOICES.new:
            self.object.state = Application.APP_STATE_CHOICES.draft
        self.object.save()
        new_loc.save()
        if self.object.app_type == self.object.APP_TYPE_CHOICES.licence:
            form.save_m2m()
        return HttpResponseRedirect(self.get_success_url())


class ApplicationLodge(LoginRequiredMixin, UpdateView):
    model = Application
    form_class = apps_forms.ApplicationLodgeForm

    def get(self, request, *args, **kwargs):
        # TODO: business logic to check the application may be lodged.
        # Rule: application state must be 'draft'.
        app = self.get_object()
        if app.state != app.APP_STATE_CHOICES.draft:
            # TODO: better/explicit error response.
            messages.error(self.request, 'This application cannot be lodged!')
            return HttpResponseRedirect(app.get_absolute_url())
        return super(ApplicationLodge, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(self.get_object().get_absolute_url())
        return super(ApplicationLodge, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        """Override form_valid to set the submit_date and status of the new application.
        """
        app = self.get_object()
        app.state = app.APP_STATE_CHOICES.with_admin
        self.object.submit_date = date.today()
        app.assignee = None
        app.save()
        # Generate a 'lodge' action:
        action = Action(
            content_object=app, category=Action.ACTION_CATEGORY_CHOICES.lodge,
            user=self.request.user, action='Application lodgement')
        action.save()
        # Success message.
        msg = """Your {0} application has been successfully submitted. The application
        number is: <strong>{1}</strong>.<br>
        Please note that routine applications take approximately 4-6 weeks to process.<br>
        If any information is unclear or missing, Parks and Wildlife may return your
        application to you to amend or complete.<br>
        The assessment process includes a 21-day external referral period. During this time
        your application may be referred to external departments, local government
        agencies or other stakeholders. Following this period, an internal report will be
        produced by an officer for approval by the Manager, Rivers and Estuaries Division,
        to determine the outcome of your application.<br>
        You will be notified by email once your {0} application has been determined and/or
        further action is required.""".format(app.get_app_type_display(), app.pk)
        messages.success(self.request, msg)
        return HttpResponseRedirect(self.get_success_url())


class ApplicationRefer(LoginRequiredMixin, CreateView):
    """A view to create a Referral object on an Application (if allowed).
    """
    model = Referral
    form_class = apps_forms.ReferralForm

    def get(self, request, *args, **kwargs):
        # TODO: business logic to check the application may be referred.
        # Rule: application state must be 'with admin' or 'with referee'
        app = Application.objects.get(pk=self.kwargs['pk'])
        if app.state not in [app.APP_STATE_CHOICES.with_admin, app.APP_STATE_CHOICES.with_referee]:
            # TODO: better/explicit error response.
            messages.error(
                self.request, 'This application cannot be referred!')
            return HttpResponseRedirect(app.get_absolute_url())
        return super(ApplicationRefer, self).get(request, *args, **kwargs)

    def get_success_url(self):
        """Override to redirect to the referral's parent application detail view.
        """
        return reverse('application_detail', args=(self.object.application.pk,))

    def get_context_data(self, **kwargs):
        context = super(ApplicationRefer, self).get_context_data(**kwargs)
        context['application'] = Application.objects.get(pk=self.kwargs['pk'])
        return context

    def get_initial(self):
        initial = super(ApplicationRefer, self).get_initial()
        # TODO: set the default period value based on application type.
        initial['period'] = 21
        return initial

    def get_form_kwargs(self):
        kwargs = super(ApplicationRefer, self).get_form_kwargs()
        kwargs['application'] = Application.objects.get(pk=self.kwargs['pk'])
        return kwargs

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            app = Application.objects.get(pk=self.kwargs['pk'])
            return HttpResponseRedirect(app.get_absolute_url())
        return super(ApplicationRefer, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        app = Application.objects.get(pk=self.kwargs['pk'])
        self.object = form.save(commit=False)
        self.object.application = app
        self.object.sent_date = date.today()
        self.object.save()
        # Set the application status to 'with referee'.
        app.state = app.APP_STATE_CHOICES.with_referee
        app.save()
        # TODO: the process of sending the application to the referee.
        # Generate a 'refer' action on the application:
        action = Action(
            content_object=app, category=Action.ACTION_CATEGORY_CHOICES.refer,
            user=self.request.user, action='Referred for conditions/feedback to {}'.format(self.object.referee))
        action.save()
        return super(ApplicationRefer, self).form_valid(form)


class ConditionCreate(LoginRequiredMixin, CreateView):
    """A view for a referee or an internal user to create a Condition object
    on an Application.
    """
    model = Condition
    form_class = apps_forms.ConditionCreateForm

    def get(self, request, *args, **kwargs):
        app = Application.objects.get(pk=self.kwargs['pk'])
        # Rule: conditions can be created when the app is with admin, with
        # referee or with assessor.
        if app.state not in [app.APP_STATE_CHOICES.with_admin, app.APP_STATE_CHOICES.with_referee, app.APP_STATE_CHOICES.with_assessor]:
            messages.error(
                self.request, 'New conditions cannot be created for this application!')
            return HttpResponseRedirect(app.get_absolute_url())
        return super(ConditionCreate, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(ConditionCreate, self).get_context_data(**kwargs)
        context['page_heading'] = 'Create a new condition'
        return context

    def get_success_url(self):
        """Override to redirect to the condition's parent application detail view.
        """
        return reverse('application_detail', args=(self.object.application.pk,))

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            app = Application.objects.get(pk=self.kwargs['pk'])
            return HttpResponseRedirect(app.get_absolute_url())
        return super(ConditionCreate, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        app = Application.objects.get(pk=self.kwargs['pk'])
        self.object = form.save(commit=False)
        self.object.application = app
        # If a referral exists for the parent application for this user,
        # link that to the new condition.
        if Referral.objects.filter(application=app, referee=self.request.user).exists():
            self.object.referral = Referral.objects.get(
                application=app, referee=self.request.user)
        # If the request user is not in the "Referee" group, then assume they're an internal user
        # and set the new condition to "applied" status (default = "proposed").
        referee = Group.objects.get(name='Referee')
        if referee not in self.request.user.groups.all():
            self.object.status = Condition.CONDITION_STATUS_CHOICES.applied
        self.object.save()
        # Record an action on the application:
        action = Action(
            content_object=app, user=self.request.user,
            action='Created condition {} (status: {})'.format(self.object.pk, self.object.get_status_display()))
        action.save()
        return super(ConditionCreate, self).form_valid(form)


class ApplicationAssign(LoginRequiredMixin, UpdateView):
    """A view to allow an application to be assigned to an internal user or back to the customer.
    The ``action`` kwarg is used to define the new state of the application.
    """
    model = Application

    def get(self, request, *args, **kwargs):
        app = self.get_object()
        if self.kwargs['action'] == 'customer':
            # Rule: application can go back to customer when only status is
            # 'with admin'.
            if app.state != app.APP_STATE_CHOICES.with_admin:
                messages.error(
                    self.request, 'This application cannot be returned to the customer!')
                return HttpResponseRedirect(app.get_absolute_url())
        if self.kwargs['action'] == 'assess':
            # Rule: application can be assessed when status is 'with admin',
            # 'with referee' or 'with manager'.
            if app.state not in [app.APP_STATE_CHOICES.with_admin, app.APP_STATE_CHOICES.with_referee, app.APP_STATE_CHOICES.with_manager]:
                messages.error(
                    self.request, 'This application cannot be assigned to an assessor!')
                return HttpResponseRedirect(app.get_absolute_url())
        # Rule: only the assignee (or a superuser) can assign for approval.
        if self.kwargs['action'] == 'approve':
            if app.state != app.APP_STATE_CHOICES.with_assessor:
                messages.error(
                    self.request, 'You are unable to assign this application for approval/issue!')
                return HttpResponseRedirect(app.get_absolute_url())
            if app.assignee != request.user and not request.user.is_superuser:
                messages.error(
                    self.request, 'You are unable to assign this application for approval/issue!')
                return HttpResponseRedirect(app.get_absolute_url())
        return super(ApplicationAssign, self).get(request, *args, **kwargs)

    def get_form_class(self):
        # Return the specified form class
        if self.kwargs['action'] == 'customer':
            return apps_forms.AssignCustomerForm
        elif self.kwargs['action'] == 'process':
            return apps_forms.AssignProcessorForm
        elif self.kwargs['action'] == 'assess':
            return apps_forms.AssignAssessorForm
        elif self.kwargs['action'] == 'approve':
            return apps_forms.AssignApproverForm

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(self.get_object().get_absolute_url())
        return super(ApplicationAssign, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        messages.success(self.request, 'Application {} has been assigned to {}'.format(
            self.object.pk, self.object.assignee.get_full_name()))
        if self.kwargs['action'] == 'customer':
            # Assign the application back to the applicant and make it 'draft'
            # status.
            self.object.assignee = self.object.applicant
            self.object.state = self.object.APP_STATE_CHOICES.draft
            # TODO: email the feedback back to the customer.
        if self.kwargs['action'] == 'assess':
            self.object.state = self.object.APP_STATE_CHOICES.with_assessor
        if self.kwargs['action'] == 'approve':
            self.object.state = self.object.APP_STATE_CHOICES.with_manager
        self.object.save()
        if self.kwargs['action'] == 'customer':
            # Record the feedback on the application:
            d = form.cleaned_data
            action = Action(
                content_object=self.object, category=Action.ACTION_CATEGORY_CHOICES.communicate, user=self.request.user,
                action='Feedback provided to applicant: {}'.format(d['feedback']))
            action.save()
        # Record an action on the application:
        action = Action(
            content_object=self.object, category=Action.ACTION_CATEGORY_CHOICES.assign, user=self.request.user,
            action='Assigned application to {} (status: {})'.format(self.object.assignee.get_full_name(), self.object.get_state_display()))
        action.save()
        return HttpResponseRedirect(self.get_success_url())


class ApplicationIssue(LoginRequiredMixin, UpdateView):
    """A view to allow a manager to issue an assessed application.
    """
    model = Application
    form_class = apps_forms.ApplicationIssueForm

    def get(self, request, *args, **kwargs):
        # Rule: only the assignee (or a superuser) can perform this action.
        app = self.get_object()
        if app.assignee == request.user or request.user.is_superuser:
            return super(ApplicationIssue, self).get(request, *args, **kwargs)
        messages.error(
            self.request, 'You are unable to issue this application!')
        return HttpResponseRedirect(app.get_absolute_url())

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(self.get_object().get_absolute_url())
        return super(ApplicationIssue, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        d = form.cleaned_data
        if d['assessment'] == 'issue':
            self.object.state = self.object.APP_STATE_CHOICES.issued
            self.object.assignee = None
            # Record an action on the application:
            action = Action(
                content_object=self.object, category=Action.ACTION_CATEGORY_CHOICES.issue,
                user=self.request.user, action='Application issued')
            action.save()
            messages.success(
                self.request, 'Application {} has been issued'.format(self.object.pk))
        elif d['assessment'] == 'decline':
            self.object.state = self.object.APP_STATE_CHOICES.declined
            self.object.assignee = None
            # Record an action on the application:
            action = Action(
                content_object=self.object, category=Action.ACTION_CATEGORY_CHOICES.decline,
                user=self.request.user, action='Application declined')
            action.save()
            messages.warning(
                self.request, 'Application {} has been declined'.format(self.object.pk))
        self.object.save()
        # TODO: logic around emailing/posting the application to the customer.
        return HttpResponseRedirect(self.get_success_url())


class ReferralComplete(LoginRequiredMixin, UpdateView):
    """A view to allow a referral to be marked as 'completed'.
    """
    model = Referral
    form_class = apps_forms.ReferralCompleteForm

    def get(self, request, *args, **kwargs):
        referral = self.get_object()
        # Rule: can't mark a referral completed more than once.
        if referral.response_date:
            messages.error(self.request, 'This referral is already completed!')
            return HttpResponseRedirect(referral.application.get_absolute_url())
        # Rule: only the referee (or a superuser) can mark a referral
        # "complete".
        if referral.referee == request.user or request.user.is_superuser:
            return super(ReferralComplete, self).get(request, *args, **kwargs)
        messages.error(
            self.request, 'You are unable to mark this referral as complete!')
        return HttpResponseRedirect(referral.application.get_absolute_url())

    def get_context_data(self, **kwargs):
        context = super(ReferralComplete, self).get_context_data(**kwargs)
        context['application'] = self.get_object().application
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(self.get_object().application.get_absolute_url())
        return super(ReferralComplete, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.response_date = date.today()
        self.object.status = Referral.REFERRAL_STATUS_CHOICES.responded
        self.object.save()
        app = self.object.application
        # Record an action on the referral's application:
        action = Action(
            content_object=app, user=self.request.user,
            action='Referral to {} marked as completed'.format(self.object.referee))
        action.save()
        # If there are no further outstanding referrals, then set the
        # application status to "with admin".
        if not Referral.objects.filter(
                application=app, status=Referral.REFERRAL_STATUS_CHOICES.referred).exists():
            app.state = Application.APP_STATE_CHOICES.with_admin
            app.save()
            # Record an action.
            action = Action(
                content_object=app,
                action='No outstanding referrals, application status set to "{}"'.format(app.get_state_display()))
            action.save()
        return HttpResponseRedirect(app.get_absolute_url())


class ReferralRecall(LoginRequiredMixin, UpdateView):
    model = Referral
    form_class = apps_forms.ReferralRecallForm
    template_name = 'applications/referral_recall.html'

    def get(self, request, *args, **kwargs):
        referral = self.get_object()
        # Rule: can't recall a referral that is any other status than
        # 'referred'.
        if referral.status != Referral.REFERRAL_STATUS_CHOICES.referred:
            messages.error(self.request, 'This referral is already completed!')
            return HttpResponseRedirect(referral.application.get_absolute_url())
        return super(ReferralRecall, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(ReferralRecall, self).get_context_data(**kwargs)
        context['referral'] = self.get_object()
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(self.get_object().application.get_absolute_url())
        return super(ReferralRecall, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.status = Referral.REFERRAL_STATUS_CHOICES.recalled
        self.object.save()
        # Record an action on the referral's application:
        action = Action(
            content_object=self.object.application, user=self.request.user,
            action='Referral to {} recalled'.format(self.object.referee))
        action.save()
        return HttpResponseRedirect(self.object.application.get_absolute_url())


class ComplianceList(ListView):
    model = Compliance

    def get_queryset(self):
        qs = super(ComplianceList, self).get_queryset()
        # Did we pass in a search string? If so, filter the queryset and return
        # it.
        if 'q' in self.request.GET and self.request.GET['q']:
            query_str = self.request.GET['q']
            # Replace single-quotes with double-quotes
            query_str = query_str.replace("'", r'"')
            # Filter by applicant__email, assignee__email, compliance
            query = get_query(
                query_str, ['applicant__email', 'assignee__email', 'compliance'])
            qs = qs.filter(query).distinct()
        return qs


class ComplianceCreate(LoginRequiredMixin, ModelFormSetView):
    model = Compliance
    form_class = apps_forms.ComplianceCreateForm
    template_name = 'applications/compliance_formset.html'
    fields = ['condition', 'compliance']

    def get_application(self):
        return Application.objects.get(pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        context = super(ComplianceCreate, self).get_context_data(**kwargs)
        app = self.get_application()
        context['application'] = app
        return context

    def get_initial(self):
        # Return a list of dicts, each containing a reference to one condition.
        app = self.get_application()
        conditions = app.condition_set.all()
        return [{'condition': c} for c in conditions]

    def get_factory_kwargs(self):
        kwargs = super(ComplianceCreate, self).get_factory_kwargs()
        app = self.get_application()
        conditions = app.condition_set.all()
        # Set the number of forms in the set to equal the number of conditions.
        kwargs['extra'] = len(conditions)
        return kwargs

    def get_extra_form_kwargs(self):
        kwargs = super(ComplianceCreate, self).get_extra_form_kwargs()
        kwargs['application'] = self.get_application()
        return kwargs

    def formset_valid(self, formset):
        for form in formset:
            data = form.cleaned_data
            # If text has been input to the compliance field, create a new
            # compliance object.
            if 'compliance' in data and data.get('compliance', None):
                new_comp = form.save(commit=False)
                new_comp.applicant = self.request.user
                new_comp.submit_date = date.today()
                # TODO: handle the uploaded file.
                new_comp.save()
                # Record an action on the compliance request's application:
                action = Action(
                    content_object=new_comp.application, user=self.request.user,
                    action='Request for compliance created')
                action.save()
        messages.success(
            self.request, 'New requests for compliance have been submitted.')
        return super(ComplianceCreate, self).formset_valid(formset)

    def get_success_url(self):
        return reverse('application_detail', args=(self.get_application().pk,))


class VesselCreate(LoginRequiredMixin, CreateView):
    model = Vessel
    form_class = apps_forms.VesselForm

    def get(self, request, *args, **kwargs):
        app = Application.objects.get(pk=self.kwargs['pk'])
        if app.state != app.APP_STATE_CHOICES.draft:
            messages.errror(
                self.request, "Can't add new vessels to this application")
            return HttpResponseRedirect(app.get_absolute_url())
        return super(VesselCreate, self).get(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('application_detail', args=(self.kwargs['pk'],))

    def get_context_data(self, **kwargs):
        context = super(VesselCreate, self).get_context_data(**kwargs)
        context['page_heading'] = 'Create new vessel details'
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            app = Application.objects.get(pk=self.kwargs['pk'])
            return HttpResponseRedirect(app.get_absolute_url())
        return super(VesselCreate, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        app = Application.objects.get(pk=self.kwargs['pk'])
        self.object = form.save()
        app.vessels.add(self.object.id)
        app.save()
        # Registration document uploads.
        if self.request.FILES.get('registration'):
            # Remove any existing documents.
            for d in self.object.registration.all():
                self.object.registration.remove(d)
            # Add new uploads.
            for f in form.cleaned_data['registration']:
                doc = Document()
                doc.upload = f
                doc.name = f.name
                doc.save()
                self.object.registration.add(doc)

        return super(VesselCreate, self).form_valid(form)


class ConditionUpdate(LoginRequiredMixin, UpdateView):
    """A view to allow an assessor to update a condition that might have been
    proposed by a referee.
    The ``action`` kwarg is used to define the new state of the condition.
    """
    model = Condition
    form_class = apps_forms.ConditionUpdateForm

    def get(self, request, *args, **kwargs):
        condition = self.get_object()
        # Rule: can only change a condition if the parent application is status
        # 'with assessor'.
        if condition.application.state != Application.APP_STATE_CHOICES.with_assessor:
            messages.error(
                self.request, 'You can only change conditions when the application is "with assessor" status')
            return HttpResponseRedirect(condition.application.get_absolute_url())
        return super(ConditionUpdate, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(ConditionUpdate, self).get_context_data(**kwargs)
        if 'action' in self.kwargs:
            if self.kwargs['action'] == 'apply':
                context['page_heading'] = 'Apply a proposed condition'
            elif self.kwargs['action'] == 'reject':
                context['page_heading'] = 'Reject a proposed condition'
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(self.get_object().application.get_absolute_url())
        return super(ConditionUpdate, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        if 'action' in self.kwargs:
            if self.kwargs['action'] == 'apply':
                self.object.status = Condition.CONDITION_STATUS_CHOICES.applied
            elif self.kwargs['action'] == 'reject':
                self.object.status = Condition.CONDITION_STATUS_CHOICES.rejected
            # Generate an action:
            action = Action(
                content_object=self.object.application, user=self.request.user,
                action='Condition {} updated (status: {})'.format(self.object.pk, self.object.get_status_display()))
            action.save()
        self.object.save()
        return HttpResponseRedirect(self.object.application.get_absolute_url())


class VesselUpdate(LoginRequiredMixin, UpdateView):
    model = Vessel
    form_class = apps_forms.VesselForm

    def get(self, request, *args, **kwargs):
        app = self.get_object().application_set.first()
        # Rule: can only change a vessel if the parent application is status 'draft'.
        if app.state != Application.APP_STATE_CHOICES.draft:
            messages.error(
                self.request, 'You can only change a vessel details when the application is "draft" status')
            return HttpResponseRedirect(app.get_absolute_url())
        return super(VesselUpdate, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(VesselUpdate, self).get_context_data(**kwargs)
        context['page_heading'] = 'Update vessel details'
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            app = self.get_object().application_set.first()
            return HttpResponseRedirect(app.get_absolute_url())
        return super(VesselUpdate, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save()
        # Registration document uploads.
        if self.request.FILES.get('registration'):
            # Remove any existing documents.
            for d in self.object.registration.all():
                self.object.registration.remove(d)
            # Add new uploads.
            for f in form.cleaned_data['registration']:
                doc = Document()
                doc.upload = f
                doc.name = f.name
                doc.save()
                self.object.registration.add(doc)
        app = self.object.application_set.first()
        return HttpResponseRedirect(app.get_absolute_url())


class DocumentCreate(LoginRequiredMixin, CreateView):
    form_class = apps_forms.DocumentCreateForm
    template_name = 'applications/document_form.html'

    def get_context_data(self, **kwargs):
        context = super(DocumentCreate, self).get_context_data(**kwargs)
        context['page_heading'] = 'Create new Document'
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('cancel'):
            return HttpResponseRedirect(reverse('home_page'))
        return super(DocumentCreate, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        """Override form_valid to set the assignee as the object creator.
        """
        self.object = form.save(commit=False)
        self.object.save()
        success_url = reverse('document_list', args=(self.object.pk,))
        return HttpResponseRedirect(success_url)


class DocumentList(ListView):
    model = Document
