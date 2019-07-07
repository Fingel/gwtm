# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify, render_template, redirect, flash, url_for
from flask_sqlalchemy import SQLAlchemy
import flask_sqlalchemy as fsq
from geoalchemy2 import Geometry
from enum import Enum

import os, json, datetime
import random

from . import function
from . import models
from . import forms
from src import app
from flask_login import current_user, login_user, logout_user, login_required
from werkzeug.urls import url_parse

db = models.db

@app.route("/index", methods=["GET"])
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/alerts", methods=['GET'])
@login_required
def alerts():
	alerts = models.gw_alert.query.filter_by(role="observation").all()
	alerts = list(set([a.graceid for a in alerts]))
	return render_template("alerts.html", alerts=alerts)


@app.route("/gw_event", methods=['GET'])
@login_required
def ligo_alert():
	#get graceID and display visulization.
	return render_template('gw_event.html', graceid=graceid)


@app.route("/contact", methods=['GET'])
def contact():
    return render_template("contact.html")


@app.route("/about", methods=['GET'])
def about():
    return render_template('about.html')


@app.route("/documentation", methods=['GET'])
def documentation():
	return render_template('documentation.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect('/index')
    form = forms.RegistrationForm()
    if form.validate_on_submit():
        user = models.users(username=form.username.data, email=form.email.data)
        user.datecreated = datetime.datetime.now()
        user.set_password(form.password.data)
        user.set_apitoken()
        db.session.add(user)
        db.session.commit()
        return redirect('/login')
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = forms.LoginForm()
    if form.validate_on_submit():
        user = models.users.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            #print("Invalid username or password")
            return redirect('login')
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = '/index'
        return redirect(next_page)
    return render_template('login.html', form=form)

@app.route('/manage_user', methods=['GET', 'POST'])
@login_required
def manage_user():

	userid = current_user.id
	user = models.users.query.filter_by(id=userid).first()
	groupfilter = []
	groupfilter.append(models.usergroups.groupid == models.groups.id)
	groupfilter.append(models.usergroups.userid == userid)
	groups = db.session.query(models.groups.name, models.usergroups.role).filter(*groupfilter).all()
	#form = froms.ManageUserForm():
	#if form.validate_on_submit():

	return render_template('manage_user.html', user=user, groups=groups)


@app.route('/logout')
def logout():
    logout_user()
    return redirect('/index')

#API Endpoints

#Post Pointing/s
#Parameters: List of Pointing JSON objects
#Returns: List of assigned IDs
#Comments: Check if instrument configuration already exists to avoid duplication. 
#Check if pointing is centered at a galaxy in one of the catalogs and if so, associate it.

@app.route("/api/v0/pointings", methods=["POST"])
def add_pointings():

	try:
		rd = request.get_json()
	except:
		return("Whoaaaa that JSON is a little wonky")
		     
	valid_gid = False

	if "graceid" in rd:
		gid = rd['graceid']
		current_gids = db.session.query(models.gw_alert.graceid).filter(models.gw_alert.graceid == gid).all()
		if len(current_gids) > 0:
			valid_gid = True
		else:
			return jsonify("Invalid graceid")
	else:
		return jsonify("graceid is required")

	if "api_token" in rd:
		apitoken = rd['api_token']
		user = db.session.query(models.users).filter(models.users.api_token ==  apitoken).first()
		if user is None:
			return jsonify("invalid api_token")
		else:
			userid = user.id
	else:
		return jsonify("api_token is required")

	dbinsts = db.session.query(models.instrument.instrument_name,
                               models.instrument.id).all()

	#dbusers = db.session.query(models.users.id,
	#						   models.users.username,
	#						   models.users.firstname,
	#						   models.users.lastname).all()

	points = []
	errors = []
	warnings = []

	if "pointing" in rd:
		p = rd['pointing']
		mp = models.pointing()
		v = mp.from_json(p, dbinsts, userid)
		if v.valid:
			points.append(mp)
			if len(v.warnings) > 0:
				warnings.append(["Object: " + json.dumps(p), v.warnings])
			db.session.add(mp)
		else:
			errors.append(["Object: "+json.dumps(p), v.errors])
            
	elif "pointings" in rd:
		pointings = rd['pointings']
		for p in pointings:
			mp = models.pointing()
			v = mp.from_json(p, dbinsts, userid)
			if v.valid:
				points.append(mp)
				db.session.add(mp)
				if len(v.warnings) > 0:
					warnings.append(["Object: " + json.dumps(p), v.warnings])
			else:
				errors.append(["Object: "+json.dumps(p), v.errors])
	else: 
		return jsonify("Invalid request: json pointing or json list of pointings are required\nYou can find API documentation here: www.treasuremap_api_documentation.com")

	db.session.flush()

	if valid_gid:
		for p in points:
			pe = models.pointing_event(
				pointingid = p.id,
				graceid = gid)
			db.session.add(pe)

	db.session.flush()
	db.session.commit()
	return jsonify({"pointing_ids":[x.id for x in points], "ERRORS":errors, "WARNINGS":warnings})

#Get Pointing/s
#Parameters: List of ID/s, type/s, group/s, user/s, and/or time/s constraints (to be AND’ed). 
#Returns: List of PlannedPointing JSON objects

@app.route("/api/v0/pointings", methods=["GET"])
def get_pointings():

	args = request.args

	filter=[]

	if "graceid" in args:
		graceid = args.get('graceid')
		filter.append(models.pointing_event.graceid == graceid)
		filter.append(models.pointing_event.pointingid == models.pointing.id)

	if "id" in args:
		_id = args.get('id')
		filter.append(models.pointing.id == int(_id))
	elif "ids" in args:
		ids = json.loads(args.get('ids'))
		filter.append(models.pointing.id.in_(ids))

	if "band" in args:
		band = args.get('band')
		filter.append(models.pointing.band == band)
	elif "bands" in args:
		bands_sent = args.get('bands')
		bands = []
		for b in models.bandpass:
			if b.name in bands_sent:
				bands.append(b)
		filter.append(models.pointing.band.in_(bands))

	if "status" in args:
		status = args.get('status')
		filter.append(models.pointing.status == status)
	elif "statuses" in args:
		statuses = []
		statuses_sent = args.get('statuses')
		if "planned" in statuses_sent:
			statuses.append(models.pointing_status.planned)
		if "completed" in statuses_sent:
			statuses.append(models.pointing_status.completed)
		if "cancelled" in statuses_sent:
			statuses.append(models.pointing_status.cancelled)
		filter.append(models.pointing.status.in_(statuses))

	if "completed_after" in args:
		time = args.get('completed_after')
		try:
			time = datetime.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S")
		except:
			return jsonify("Error parsing date. Should be %Y-%m-%dT%H:%M:%S format. e.g. 2019-05-01T12:00:00")
		filter.append(models.pointing.status == models.pointing_status.completed)
		filter.append(models.pointing.time >= time)

	if "completed_before" in args:
		time = args.get('completed_before')
		try:
			time = datetime.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S")
		except:
			return jsonify("Error parsing date. Should be %Y-%m-%dT%H:%M:%S format. e.g. 2019-05-01T12:00:00")
		filter.append(models.pointing.status == models.pointing_status.completed)
		filter.append(models.pointing.time <= time)

	if "planned_after" in args:
		time = args.get('planned_after')
		try:
			time = datetime.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S")
		except:
			return jsonify("Error parsing date. Should be %Y-%m-%dT%H:%M:%S format. e.g. 2019-05-01T12:00:00")
		filter.append(models.pointing.status == models.pointing_status.planned)
		filter.append(models.pointing.time >= time)

	if "planned_before" in args:
		time = args.get('planned_before')
		try:
			time = datetime.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S")
		except:
			return jsonify("Error parsing date. Should be %Y-%m-%dT%H:%M:%S format. e.g. 2019-05-01T12:00:00")
		filter.append(models.pointing.status == models.pointing_status.planned)
		filter.append(models.pointing.time <= time)

	if "group" in args:
		group = args.get('group')
		if group.isdigit():
			filter.append(models.usergroups.groupid == group)
		else:
			filter.append(models.groups.name.contains(group))
			filter.append(models.usergroups.groupid == models.groups.id)

		filter.append(models.usergroups.userid == models.users.id)
		filter.append(models.users.id == models.pointing.submitterid)

	elif "groups" in args:
		try:
			groups = json.loads(args.get('groups'))
			filter.append(models.usergroups.groupid.in_(groups))
		except:
			groups = args.get('groups')
			groups = groups.split('[')[1].split(']')[0].split(',')
			ors = []
			print(groups)
			for g in groups:
				ors.append(models.groups.name.contains(g.strip()))
			filter.append(fsq.sqlalchemy.or_(*ors))
			filter.append(models.usergroups.groupid == models.groups.id)
		filter.append(models.usergroups.userid == models.users.id)
		filter.append(models.users.id == models.pointing.submitterid)

	if "user" in args:
		user = args.get('user')
		if user.isdigit():
			filter.append(models.pointing.submitterid == int(user))
		else:
			filter.append(fsq.sqlalchemy.or_(models.users.username.contains(user),
							  models.users.firstname.contains(user),
							  models.users.lastname.contains(user)))
			filter.append(models.users.id == models.pointing.submitterid)

	if "users" in args:
		try:
			users = json.loads(args.get('users'))
			filter.append(models.pointing.submitterid.in_(users))
		except:
			users = args.get('users')
			users = users.split('[')[1].split(']')[0].split(',') 
			ors = []
			for u in users:
				ors.append(models.users.username.contains(u.strip()))
				ors.append(models.users.firstname.contains(u.strip()))
				ors.append(models.users.lastname.contains(u.strip()))
			filter.append(fsq.sqlalchemy.or_(*ors))
			filter.append(models.users.id == models.pointing.submitterid)
	
	if "instrument" in args:
		inst = args.get('instrument')
		if inst.isdigit():
			filter.append(models.pointing.instrumentid == int(inst))
		else:
			filter.append(models.pointing.instrumentid == models.instrument.id)
			filter.append(models.instrument.instrument_name.contains(inst))

	if "instruments" in args:
		try:
			insts = json.loads(args.get('instruments'))
			filter.append(models.pointing.instrumentid.in_(insts))
		except:
			insts = args.get('instruments')
			insts = insts.split('[')[1].split(']')[0].split(',') 
			ors = []
			for i in insts:
				ors.append(models.instrument.instrument_name.contains(i.strip()))
			filter.append(fsq.sqlalchemy.or_(*ors))
			filter.append(models.instrument.id == models.pointing.instrumentid)

	pointings = db.session.query(models.pointing).filter(*filter).all()
	pointings = [x.json for x in pointings]

	return jsonify(pointings)

#Cancel PlannedPointing
#Parameters: List of IDs of planned pointings for which it is known that they aren’t going to happen

@app.route("/api/v0/pointings", methods=["DELETE"])
def del_pointings():
	args = request.args


	if "api_token" in args:
		apitoken = arg['api_token']
		user = db.session.query(models.users).filter(models.users.api_token ==  apitoken).first()
		if user is None:
			return jsonify("invalid api_token")

	filter1 = []
	filter2 = []
	if "id" in args:
		filter1.append(models.pointing.id == int(args.get('id')))
		filter2.append(models.pointing_event.pointingid == int(args.get('id')))
	if "ids" in args:
		filter1.append(models.pointing.id.in_(json.loads(args.get('ids'))))
		filter2.append(models.pointing_event.pointingid.in_(json.loads(args.get('ids'))))

	#valid_api_token = validate_api_token(args)

	if len(filter1) > 0: #and valid_api_token:
		pointings = db.session.query(models.pointing).filter(*filter1)
		pointings.delete(synchronize_session=False)

		pointing_es = db.session.query(models.pointing_event).filter(*filter2)
		pointing_es.delete(synchronize_session=False)



		db.session.commit()
		return jsonify("Deleted Pointings successfully")

	else:
		return jsonify("Please Don't delete the ENTIRE POINTING table")


#@app.route("/instruments", methods=["POST"])
#def post_instruments():
#	return jsonify("success")


#Get Instrument/s
#Parameters: List of ID/s, type/s (to be AND’ed).
#Returns: List of Instrument JSON objects

@app.route("/api/v0/instruments", methods=["GET"])
def get_instruments():

	args = request.args

	filter=[]
	if "id" in args:
		#validate
		_id = args.get('id')
		filter.append(models.instrument.id == int(_id))
	if "ids" in args:
		#validate
		ids = json.loads(args.get('ids'))
		print(ids)
		filter.append(models.instrument.id.in_(ids))
	if "name" in args:
		name = args.get('name')
		filter.append(models.instrument.instrument_name.contains(name))
	if "names" in args:
		insts = args.get('instruments')
		insts = insts.split('[')[1].split(']')[0].split(',') 
		ors = []
		for i in insts:
			ors.append(models.instrument.instrument_name.contains(i.strip()))
		filter.append(fsq.sqlalchemy.or_(*ors))
		filter.append(models.instrument.id == models.pointing.instrumentid)

	if "type" in args:
		#validate
		_type = args.get('type')
		filter.append(models.instrument.instrument_type == _type)

	insts = db.session.query(models.instrument).filter(*filter).all()
	insts = [x.json for x in insts]

	return jsonify(insts)

#Post Candidate/s
#Parameters: List of Candidate JSON objects
#Returns: List of assigned IDs
#Notes: Check if a candidate already exists at these coordinates (with a 2” tolerance) and if so, just add the name to the names table (if new).

#Get Candidate/s
#Parameters: List of ID/s, name/s, group/s, user/s, time/s, RA, Dec (to be AND’ed).
#Returns: List of Candidate JSON objects

#Post Photometry
#Parameters: List of Photometry JSON objects
#Returns: List of assigned IDs

#Get Photometry
#Parameters: List of candidate ID/s, time/s, magnitude/s, filter/s (to be AND’ed).
#Returns: List of Photometry JSON objects

#Post Spectroscopy
#Parameters: List of Spectroscopy JSON objects
#Returns: List of assigned IDs

#Get Spectroscopy
#Parameters: List of candidate ID/s, time/s (to be AND’ed).
#Returns: List of Spectroscopy JSON objects
