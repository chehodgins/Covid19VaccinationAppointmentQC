import json
import time

from datetime import datetime, timedelta
from urllib import parse
from zoneinfo import ZoneInfo

import requests

import sys
MIN_PYTHON = (3, 9)
assert sys.version_info >= MIN_PYTHON, f"requires Python {'.'.join([str(n) for n in MIN_PYTHON])} or newer"

DEBUG = False

url_geocode = 'https://api3.clicsante.ca/v3/geocode?address={postal_code}'
url_availabilities = 'https://api3.clicsante.ca/v3/availabilities?dateStart={start_date}&dateStop={end_date}&latitude={latitude}&longitude={longitude}&maxDistance={max_distance}&serviceUnified=237&postalCode={postal_code}&page={page}'
url_services = 'https://api3.clicsante.ca/v3/establishments/{establishment}/services'
url_public_schedules = 'https://api3.clicsante.ca/v3/establishments/{establishment}/schedules/public?dateStart={start_date}&dateStop={end_date}&service={service}&timezone=America/Toronto&places={places}&filter1=1&filter2=0'
url_day = 'https://api3.clicsante.ca/v3/establishments/{establishment}/schedules/day?dateStart={start_date}&dateStop={end_date}&service={service}&timezone=America/Toronto&places={places}&filter1=1&filter2=0'
url_browser = 'https://clients3.clicsante.ca/{establishment}/take-appt?unifiedService=237&portalPlace={place}&portalPostalCode={postal_code}&lang=fr'

postal_code = input('Enter your postal code: ')
if postal_code == '':
	exit('Missing postal code')

max_distance = input('Enter the max distance from your postal code to search in kilometers (default 200): ')
if max_distance == '':
	max_distance = 200

max_hours = input('Enter the max number of hours from now to show appointments (1 week = 168 hours. Default = 48): ')
if max_hours == '':
	max_hours = 48
else:
	max_hours = int(max_hours)

include_astrazeneca = input('Include AstraZeneca in search results (y/n - default n)? ')
if include_astrazeneca == 'y' or include_astrazeneca == 'yes':
	include_astrazeneca = True
else:
	include_astrazeneca = False

standard_headers = {'Authorization': 'Basic cHVibGljQHRyaW1vei5jb206MTIzNDU2Nzgh',
					'x-trimoz-role': 'public',
					'product': 'clicsante',
					'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36'}

print("Fetching availabilities...")

try:
	result = requests.get(url_geocode.format(postal_code=parse.quote_plus(postal_code.upper())),
		headers=standard_headers,
		timeout=10)
except requests.exceptions.ConnectionError:
	print("connection error on geocode")
	exit()

result_json = json.loads(result.text)

lat = result_json['results'][0]['geometry']['location']['lat']
lng = result_json['results'][0]['geometry']['location']['lng']

today = datetime.today()
end_date = today + timedelta(hours=max_hours)

page = 0

t07s = []
ta7s = []
while page < 5:
	try:
		url = url_availabilities.format(
			start_date=today.strftime('%Y-%m-%d'),
			end_date=end_date.strftime('%Y-%m-%d'),
			latitude=lat,
			longitude=lng,
			postal_code=parse.quote_plus(postal_code.upper()),
			page=page,
			max_distance=max_distance)

		if DEBUG:
			print(url)

		result = requests.get(url,
			headers=standard_headers,
			timeout=10)
	except requests.exceptions.ConnectionError:
		print("connection error on availabilities: {}".format(url))
		exit()

	result_json = json.loads(result.text)
	page = page + 1

	#print(result_json['places'])
	for place in result_json['places']:

		if not include_astrazeneca and 'astrazeneca' in place['name_en'].lower():
			continue

		t07 = place['availabilities']['su237']['t07']
		ta7 = place['availabilities']['su237']['ta7']

		if t07 is not None and t07 > 0:
			if DEBUG:
				print("{} has availabilities in the next 7 days".format(place['name_en']))
			t07s.append(place)
		elif ta7 is not None and ta7 > 0:
			ta7s.append(place)

availabilities = []
for place in t07s:

	# get service number
	url = url_services.format(establishment=place['establishment'])
	try:
		response = requests.get(url,
			headers=standard_headers,
			timeout=10)
	except requests.exceptions.ConnectionError:
		print("connection error on establishment services: {}".format(url))
		exit()

	result_json = json.loads(response.text)
	service = result_json[0]['id']

	url = url_public_schedules.format(establishment=place['establishment'],
  							   start_date=today.strftime('%Y-%m-%d'),
							   end_date=end_date.strftime('%Y-%m-%d'),
							   service=service,
							   places=place['id'])
	if DEBUG:
		print(url)

	try:
		response = requests.get(url,
			headers=standard_headers,
			timeout=10)
	except requests.exceptions.Timeout:
		print("timeout error on establishment availabilities for {} {}".format(place['establishment'], url))
		continue
	except requests.exceptions.ConnectionError:
		print("connection error on establishment availabilities for {} {}".format(place['establishment'], url))
		continue

	result_json = json.loads(response.text)
	#print(result_json)
	for availability in result_json['availabilities']:

		url = url_day.format(establishment=place['establishment'],
  							 start_date=today.strftime('%Y-%m-%d'),
							 end_date=end_date.strftime('%Y-%m-%d'),
							 service=service,
							 places=place['id'])
		if DEBUG:
			print(url)

		try:
			response = requests.get(url,
				headers=standard_headers,
				timeout=10)
		except requests.exceptions.ConnectionError:
			print("connection error on day availabilities: {}".format(url))
			exit()

		inner_result_json = json.loads(response.text)
		availabilities.append([availability, place, inner_result_json['availabilities']])
		break   # We're only doing the first day of availabilities for each location

	time.sleep(0.5)

# sort by date
availabilities.sort(key=lambda x: x[0])

counter = 1
print("\n")

for availability in availabilities:
	date, place, hours = availability

	# Format 2021-05-12T14:10:00+00:00
	utc_unaware = datetime.strptime(hours[0]['start'], '%Y-%m-%dT%H:%M:%S+00:00')
	utc_aware = utc_unaware.replace(tzinfo=ZoneInfo('UTC'))  # make aware
	local_aware = utc_aware.astimezone(ZoneInfo('America/Montreal'))  # convert

	print("{}. {} has {} availabilities in the next 7 days. The next availability is {}".format(
		counter,
		place['name_en'],
		place['availabilities']['su237']['t07'],
		local_aware.strftime('%Y-%m-%d %H:%M:%S EST')))
	counter = counter + 1

print("\n")

if len(availabilities) == 0:
	print("No availabilities in the next {} hours. Try later, a different postal code, or increase your search radius".format(max_hours))
else:
	while True:
		idx = input("\nEnter a number above to get the booking URL (1-{}): ".format(len(availabilities)))
		idx = int(idx)
		if idx < 1 or idx > len(availabilities) + 1:
			print("Invalid input")
		else:
			print(url_browser.format(establishment=availabilities[idx-1][1]['establishment'],
									 place=availabilities[idx-1][1]['id'],
									 postal_code=parse.quote_plus(postal_code.upper())))