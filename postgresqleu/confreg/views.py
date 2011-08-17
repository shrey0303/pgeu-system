from django.shortcuts import render_to_response, get_object_or_404
from django.http import HttpResponseRedirect, HttpResponse, Http404
from django.template import RequestContext
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.db import transaction

from models import *
from forms import *

from datetime import datetime, timedelta
import base64
import sys

#
# The ConferenceContext allows overriding of the 'conftemplbase' variable,
# which is used to control the base template of all the confreg web pages.
# This allows a single conference to override the "framework" template
# around itself, while retaining all teh contents.
#
def ConferenceContext(request, conference):
	d = RequestContext(request)
	if conference and conference.template_override:
		conftemplbase = conference.template_override
	else:
		conftemplbase = "nav_events.html"
	d.update({
			'conftemplbase': conftemplbase,
			})

	# Check if there is any additional data to put into the context
	if conference and conference.templatemodule:
		pathsave = sys.path
		sys.path.insert(0, conference.templatemodule)
		try:
			m = __import__('templateextra', globals(), locals(), ['context_template_additions'])
			d.update(m.context_template_additions())
		except Exception, ex:
			# Ignore problems, because we're lazy. Better render without the
			# data than not render at all.
			pass
		sys.path = pathsave

	return d

@login_required
def home(request, confname):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))
	conference = get_object_or_404(Conference, urlname=confname)

	if not conference.active:
		if not conference.testers.filter(pk=request.user.id):
			return render_to_response('confreg/closed.html', {
					'conference': conference,
			}, context_instance=ConferenceContext(request, conference))

	try:
		reg = ConferenceRegistration.objects.get(conference=conference,
			attendee=request.user)
	except:
		# No previous regisration, grab some data from the user profile
		reg = ConferenceRegistration(conference=conference, attendee=request.user)
		reg.email = request.user.email
		namepieces = request.user.first_name.rsplit(None,2)
		if len(namepieces) == 2:
			reg.firstname = namepieces[0]
			reg.lastname = namepieces[1]
		else:
			reg.firstname = request.user.first_name
		# If conference is set to autoapprove, then autoapprove
		if conference.autoapprove:
			reg.payconfirmedat = datetime.today()
			reg.payconfirmedby = 'auto'

	form_is_saved = False
	if request.method == 'POST':
		form = ConferenceRegistrationForm(data=request.POST, instance=reg)
		if form.is_valid():
			reg = form.save(commit=False)
			reg.conference = conference
			reg.attendee = request.user
			reg.save()
			form.save_m2m()
			form_is_saved = True
	else:
		# This is just a get, so render the form
		form = ConferenceRegistrationForm(instance=reg)

	return render_to_response('confreg/regform.html', {
		'form': form,
		'form_is_saved': form_is_saved,
		'reg': reg,
		'conference': conference,
		'additionaloptions': conference.conferenceadditionaloption_set.all(),
		'costamount': reg.regtype and reg.regtype.cost or 0,
		'payoptions': [{'name': p.name, 'infotext': p.infotext.replace('{{regid}}', str(reg.id)), 'paypalrecip': p.paypalrecip} for p in conference.paymentoptions.all()],
	}, context_instance=ConferenceContext(request, conference))

def feedback_available(request):
	conferences = Conference.objects.filter(feedbackopen=True).order_by('startdate')
	return render_to_response('confreg/feedback_available.html', {
		'conferences': conferences,
	}, context_instance=RequestContext(request))

@login_required
def feedback(request, confname):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))
	conference = get_object_or_404(Conference, urlname=confname)

	if not conference.feedbackopen:
		# Allow conference testers to override
		if not conference.testers.filter(pk=request.user.id):
			return render_to_response('confreg/feedbackclosed.html', {
					'conference': conference,
			}, context_instance=ConferenceContext(request, conference))
		else:
			is_conf_tester = True
	else:
		is_conf_tester = False

	# Figure out if the user is registered
	try:
		r = ConferenceRegistration.objects.get(conference=conference, attendee=request.user)
	except ConferenceRegistration.DoesNotExist, e:
		return HttpResponse('You are not registered for this conference.')

	if not r.payconfirmedat:
		if r.regtype.cost != 0:
			return HttpResponse('You are not a confirmed attendee of this conference.')

	# Generate a list of all feedback:able sessions, meaning all sessions that have already started,
	# since you can't give feedback on something that does not yet exist.
	if is_conf_tester:
		sessions = ConferenceSession.objects.select_related().filter(conference=conference).filter(can_feedback=True).filter(status=1)
	else:
		sessions = ConferenceSession.objects.select_related().filter(conference=conference).filter(can_feedback=True).filter(starttime__lte=datetime.now()).filter(status=1)

	# Then get a list of everything this user has feedbacked on
	feedback = ConferenceSessionFeedback.objects.filter(conference=conference, attendee=request.user)

	# Since we can't trick django to do a LEFT JOIN for us here, implement that part
	# in code here. The number of sessions is always going to be low, so it won't
	# be too big a performance issue.
	for s in sessions:
		fb = [f for f in feedback if f.session==s]
		if len(fb):
			s.has_feedback = True

	return render_to_response('confreg/feedback_index.html', {
		'sessions': sessions,
		'conference': conference,
		'is_tester': is_conf_tester,
	}, context_instance=ConferenceContext(request, conference))

@login_required
def feedback_session(request, confname, sessionid):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))
	# Room for optimization: don't get these as separate steps
	conference = get_object_or_404(Conference, urlname=confname)
	session = get_object_or_404(ConferenceSession, pk=sessionid, conference=conference, status=1)

	if not conference.feedbackopen:
		# Allow conference testers to override
		if not conference.testers.filter(pk=request.user.id):
			return render_to_response('confreg/feedbackclosed.html', {
					'conference': conference,
			}, context_instance=ConferenceContext(request, conference))
		else:
			is_conf_tester = True
	else:
		is_conf_tester = False

	if session.starttime > datetime.now() and not is_conf_tester:
		return render_to_response('confreg/feedbacknotyet.html', {
			'conference': conference,
			'session': session,
		}, context_instance=ConferenceContext(request, conference))

	try:
		feedback = ConferenceSessionFeedback.objects.get(conference=conference, session=session, attendee=request.user)
	except ConferenceSessionFeedback.DoesNotExist, e:
		feedback = ConferenceSessionFeedback()

	if request.method=='POST':
		form = ConferenceSessionFeedbackForm(data=request.POST, instance=feedback)
		if form.is_valid():
			feedback = form.save(commit=False)
			feedback.conference = conference
			feedback.attendee = request.user
			feedback.session = session
			feedback.save()
			return HttpResponseRedirect('..')
	else:
		form = ConferenceSessionFeedbackForm(instance=feedback)

	return render_to_response('confreg/feedback.html', {
		'session': session,
		'form': form,
		'conference': conference,
	}, context_instance=ConferenceContext(request, conference))


@login_required
@transaction.commit_on_success
def feedback_conference(request, confname):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))

	conference = get_object_or_404(Conference, urlname=confname)

	if not conference.feedbackopen:
		# Allow conference testers to override
		if not conference.testers.filter(pk=request.user.id):
			return render_to_response('confreg/feedbackclosed.html', {
					'conference': conference,
			}, context_instance=ConferenceContext(request, conference))
		else:
			is_conf_tester = True
	else:
		is_conf_tester = False

	# Get all questions
	questions = ConferenceFeedbackQuestion.objects.filter(conference=conference)

	# Get all current responses
	responses = ConferenceFeedbackAnswer.objects.filter(conference=conference, attendee=request.user)

	if request.method=='POST':
		form = ConferenceFeedbackForm(data=request.POST, questions=questions, responses=responses)
		if form.is_valid():
			# We've got the data, now write it to the database.
			for q in questions:
				a,created = ConferenceFeedbackAnswer.objects.get_or_create(conference=conference, question=q, attendee=request.user)
				if q.isfreetext:
					a.textanswer = form.cleaned_data['question_%s' % q.id]
				else:
					a.rateanswer = form.cleaned_data['question_%s' % q.id]
				a.save()
			return HttpResponseRedirect('..')
	else:
		form = ConferenceFeedbackForm(questions=questions, responses=responses)

	return render_to_response('confreg/feedback_conference.html', {
		'session': session,
		'form': form,
		'conference': conference,
	}, context_instance=ConferenceContext(request, conference))


class SessionSet(object):
	def __init__(self):
		self.headersize = 30
		self.rooms = {}
		self.tracks = {}
		self.sessions = []
		self.firsttime = datetime(2999,1,1)
		self.lasttime = datetime(1970,1,1)

	def add(self, session):
		if not self.rooms.has_key(session.room):
			if not session.cross_schedule:
				self.rooms[session.room] = len(self.rooms)
		if not self.tracks.has_key(session.track):
			self.tracks[session.track] = session.track
		if session.starttime < self.firsttime:
			self.firsttime = session.starttime
		if session.endtime > self.lasttime:
			self.lasttime = session.endtime
		self.sessions.append(session)

	def all(self):
		for s in self.sessions:
			if not s.cross_schedule:
				yield {
					'id': s.id,
					'title': s.title,
					'speakers': s.speaker.all(),
					'timeslot': "%s - %s" % (s.starttime.strftime("%H:%M"), s.endtime.strftime("%H:%M")),
					'track': s.track,
					'leftpos': self.roomwidth()*self.rooms[s.room],
					'toppos': self.timediff_to_y_pixels(s.starttime, self.firsttime)+self.headersize,
					'widthpos': self.roomwidth()-2,
					'heightpos': self.timediff_to_y_pixels(s.endtime, s.starttime),
				}
			else:
				yield {
					'title': s.title,
					'timeslot': "%s - %s" % (s.starttime.strftime("%H:%M"), s.endtime.strftime("%H:%M")),
					'track': s.track,
					'leftpos': 0,
					'toppos': self.timediff_to_y_pixels(s.starttime, self.firsttime)+self.headersize,
					'widthpos': self.roomwidth() * len(self.rooms) - 2,
					'heightpos': self.timediff_to_y_pixels(s.endtime, s.starttime)-2,
				}

	def schedule_height(self):
		return self.timediff_to_y_pixels(self.lasttime, self.firsttime)+2+self.headersize

	def schedule_width(self):
		if len(self.rooms):
			return self.roomwidth()*len(self.rooms)
		else:
			return 0

	def roomwidth(self):
		return int(600/len(self.rooms))

	def timediff_to_y_pixels(self, t, compareto):
		return ((t - compareto).seconds/60)*1.5

	def alltracks(self):
		return self.tracks

	def allrooms(self):
		return [{
			'name': r.roomname,
			'leftpos': self.roomwidth()*self.rooms[r],
			'widthpos': self.roomwidth()-2,
			'heightpos': self.headersize-2,
		} for r in self.rooms]

def schedule(request, confname):
	conference = get_object_or_404(Conference, urlname=confname)
	daylist = ConferenceSession.objects.filter(conference=conference, status=1).dates('starttime', 'day')
	days = []
	tracks = {}
	for d in daylist:
		sessions = ConferenceSession.objects.select_related('track','room','speaker').filter(conference=conference,status=1,starttime__range=(d,d+timedelta(hours=23,minutes=59,seconds=59))).order_by('starttime','room__roomname')
		sessionset = SessionSet()
		for s in sessions: sessionset.add(s)
		days.append({
			'day': d,
			'sessions': sessionset.all(),
			'rooms': sessionset.allrooms(),
			'schedule_height': sessionset.schedule_height(),
			'schedule_width': sessionset.schedule_width(),
		})
		tracks.update(sessionset.alltracks())

	return render_to_response('confreg/schedule.html', {
		'conference': conference,
		'days': days,
		'tracks': tracks,
	}, context_instance=ConferenceContext(request, conference))

def schedule_ical(request, confname):
	conference = get_object_or_404(Conference, urlname=confname)
	sessions = ConferenceSession.objects.filter(conference=conference).filter(cross_schedule=False).filter(status=1).order_by('starttime')
	return render_to_response('confreg/schedule.ical', {
		'conference': conference,
		'sessions': sessions,
		'servername': request.META['SERVER_NAME'],
	}, mimetype='text/calendar', context_instance=RequestContext(request))

def session(request, confname, sessionid, junk=None):
	conference = get_object_or_404(Conference, urlname=confname)
	session = get_object_or_404(ConferenceSession, conference=conference, pk=sessionid, cross_schedule=False, status=1)
	return render_to_response('confreg/session.html', {
		'conference': conference,
		'session': session,
	}, context_instance=ConferenceContext(request, conference))

def speaker(request, confname, speakerid, junk=None):
	conference = get_object_or_404(Conference, urlname=confname)
	speaker = get_object_or_404(Speaker, pk=speakerid)
	sessions = ConferenceSession.objects.filter(conference=conference, speaker=speaker, cross_schedule=False, status=1).order_by('starttime')
	if len(sessions) < 1:
		raise Http404("Speaker has no sessions at this conference")
	return render_to_response('confreg/speaker.html', {
		'conference': conference,
		'speaker': speaker,
		'sessions': sessions,
	}, context_instance=ConferenceContext(request, conference))

def speakerphoto(request, speakerid):
	speakerphoto = get_object_or_404(Speaker_Photo, pk=speakerid)
	return HttpResponse(base64.b64decode(speakerphoto.photo), mimetype='image/jpg')

@login_required
def speakerprofile(request, confurlname=None):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))

	speaker = conferences = callforpapers = None
	try:
		speaker = get_object_or_404(Speaker, user=request.user)
		conferences = Conference.objects.filter(conferencesession__speaker=speaker).distinct()
		callforpapers = Conference.objects.filter(callforpapersopen=True)
	except Speaker.DoesNotExist:
		speaker = None
		conferences = []
		callforpapers = None
	except Exception, e:
		pass

	if request.method=='POST':
		# Attempt to save
		# If this is a new speaker, create an instance for it
		if not speaker:
			speaker = Speaker(user=request.user, fullname=request.user.first_name)
			speaker.save()

		form = SpeakerProfileForm(data=request.POST, files=request.FILES, instance=speaker)
		if form.is_valid():
			if request.FILES.has_key('photo'):
				raise Exception("Deal with the file!")
			form.save()
			return HttpResponseRedirect('.')
	else:
		form = SpeakerProfileForm(instance=speaker)

	if confurlname:
		context = ConferenceContext(request,
									get_object_or_404(Conference, urlname=confurlname))
	else:
		context = ConferenceContext(request, None)
	return render_to_response('confreg/speakerprofile.html', {
			'speaker': speaker,
			'conferences': conferences,
			'callforpapers': callforpapers,
			'form': form,
	}, context_instance=context)

@login_required
def callforpapers(request, confname):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))

	conference = get_object_or_404(Conference, urlname=confname)
	if not conference.callforpapersopen:
		raise Http404('This conference has no open call for papers')

	try:
		speaker = Speaker.objects.get(user=request.user)
		sessions = ConferenceSession.objects.filter(conference=conference, speaker=speaker)
	except Speaker.DoesNotExist:
		sessions = []

	return render_to_response('confreg/callforpapers.html', {
			'conference': conference,
			'sessions': sessions,
	}, context_instance=ConferenceContext(request, conference))

@login_required
@transaction.commit_on_success
def callforpapers_new(request, confname):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))

	conference = get_object_or_404(Conference, urlname=confname)
	if not conference.callforpapersopen:
		raise Http404('This conference has no open call for papers')

	if not request.POST.has_key('title'):
		raise Http404('Title not specified')
	if len(request.POST['title']) < 1:
		raise Http404('Title not specified')

	# Find the speaker, or create
	speaker, created = Speaker.objects.get_or_create(user=request.user)
	if created:
		speaker.fullname = request.user.first_name
		speaker.save()

	s = ConferenceSession(conference=conference,
						  title=request.POST['title'],
						  status=0,
						  initialsubmit=datetime.now())
	s.save()

	# Add speaker (must be saved before we can do that)
	s.speaker.add(speaker)
	s.save()

	# Redirect back
	return HttpResponseRedirect("../%s/" % s.id)

@login_required
def callforpapers_edit(request, confname, sessionid):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))


	conference = get_object_or_404(Conference, urlname=confname)
	if not conference.callforpapersopen:
		raise Http404('This conference has no open call for papers')

	# Find users speaker record (should always exist when we get this far)
	speaker = get_object_or_404(Speaker, user=request.user)

	# Find the session record (should always exist when we get this far)
	session = get_object_or_404(ConferenceSession, conference=conference,
								speaker=speaker, pk=sessionid)

	if request.method == 'POST':
		# Save it!
		form = CallForPapersForm(data=request.POST, instance=session)
		if form.is_valid():
			form.save()
			return HttpResponseRedirect("..")
	else:
		# GET --> render empty form
		form = CallForPapersForm(instance=session)

	return render_to_response('confreg/callforpapersform.html', {
			'form': form,
			'session': session,
			'conference': conference,
	}, context_instance=ConferenceContext(request, conference))
