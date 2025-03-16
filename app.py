'''
ANDY ELIAS
PROJECT MAPPY3
DATE MARCH 12 2025
MAPPY + WEATHER + DATES + ELEVATION MAP + WEB DEV
'''

# IMPORTS

from dateutil.relativedelta import relativedelta
from flask import Flask, request, render_template_string, send_from_directory
import gpxpy
import csv
from geopy.distance import geodesic
import folium
import requests
from datetime import datetime
import os

app = Flask(__name__)


class Weather:
    def __init__(self, lat, lon, start_date, end_date):
        with open("api_key.txt", "r") as file:
            self.api_key = file.read().strip()
        self.location = [lat, lon]
        self.start_date = datetime.strptime(start_date, '%Y-%m-%d')
        self.end_date = datetime.strptime(end_date, '%Y-%m-%d')

    def weather_data(self):
        start_timestamp = int(self.start_date.timestamp())
        end_timestamp = int(self.end_date.timestamp())
        weather_url = f"https://history.openweathermap.org/data/2.5/history/city?lat={self.location[0]}&lon={self.location[1]}&type=hour&start={start_timestamp}&end={end_timestamp}&appid={self.api_key}"
        result = requests.get(weather_url)

        if result.status_code == 200:
            data = result.json()
            daily_data = {}

            for entry in data["list"]:
                date = datetime.utcfromtimestamp(entry["dt"]).strftime('%Y-%m-%d')
                temperature = entry["main"]["temp"]
                weather_description = entry["weather"][0]["description"]

                if date not in daily_data:
                    daily_data[date] = {
                        "temperatures": [],
                        "descriptions": []
                    }

                daily_data[date]["temperatures"].append(temperature)
                daily_data[date]["descriptions"].append(weather_description)

            weather_summary = []
            for date, values in daily_data.items():
                avg_temp = sum(values["temperatures"]) / len(values["temperatures"])
                c_avg_temp = round((avg_temp - 273.15) * 1.8 + 32, 2)
                common_description = max(set(values["descriptions"]), key=values["descriptions"].count)
                weather_summary.append((date, c_avg_temp, common_description))

            return weather_summary
        else:
            print(f"Error fetching weather data: {result.status_code}")
            return []


class GPXToMap:
    def __init__(self, gpx_file, csv_file):
        self.gpx_file = gpx_file
        self.csv_file = csv_file
        self.gpx_data = self._parse_gpx()
        self.csv_data = self._parse_csv()

    def _parse_gpx(self):
        with open(self.gpx_file, 'r') as file:
            gpx = gpxpy.parse(file)
        return gpx

    def _parse_csv(self):
        csv_data = []
        with open(self.csv_file, 'r') as file:
            reader = csv.reader(file)
            next(reader)  # Skip header row
            for row in reader:
                latitude, longitude, label = row
                csv_data.append((float(latitude), float(longitude), label))
        return csv_data

    def _split_segments_by_distance(self, segment, min_distance_miles, max_distance_miles):
        new_segments = []
        current_segment = []
        total_distance = 0

        for i in range(len(segment.points) - 1):
            point1 = segment.points[i]
            point2 = segment.points[i + 1]
            distance = geodesic((point1.latitude, point1.longitude), (point2.latitude, point2.longitude)).miles
            total_distance += distance

            current_segment.append((point1.latitude, point1.longitude))

            if total_distance >= max_distance_miles:
                # Calculate the exact point where the segment should end
                excess_distance = total_distance - max_distance_miles
                ratio = (distance - excess_distance) / distance
                intermediate_lat = point1.latitude + ratio * (point2.latitude - point1.latitude)
                intermediate_lon = point1.longitude + ratio * (point2.longitude - point1.longitude)
                current_segment.append((intermediate_lat, intermediate_lon))
                new_segments.append(current_segment)
                current_segment = [(intermediate_lat, intermediate_lon)]
                total_distance = excess_distance
            elif total_distance >= min_distance_miles:
                current_segment.append((point2.latitude, point2.longitude))

        if current_segment:
            new_segments.append(current_segment)

        return new_segments

    def _find_nearest_csv_point(self, point):
        nearest_point = None
        min_distance = float('inf')
        for lat, lon, label in self.csv_data:
            distance = geodesic(point, (lat, lon)).miles
            if distance < min_distance:
                min_distance = distance
                nearest_point = (lat, lon, label)
        return nearest_point

    def create_map(self, max_miles, min_miles, start_date, end_date, output_file='static/map.html'):
        # Create a map centered at the first point
        first_point = self.gpx_data.tracks[0].segments[0].points[0]
        map_center = [first_point.latitude, first_point.longitude]
        my_map = folium.Map(location=map_center, zoom_start=13)

        previous_end_point = None
        # Add CSV points to the map
        for lat, lon, label in self.csv_data:
            folium.Marker(location=[lat, lon], popup=label, icon=folium.Icon(color='blue')).add_to(my_map)

        # Add GPX points to the map
        DAY = 1
        for track in self.gpx_data.tracks:
            for segment in track.segments:
                segments = self._split_segments_by_distance(segment, min_miles, max_miles)
                for seg in segments:
                    if len(seg) > 1:
                        folium.PolyLine(seg, color="purple", weight=2.5, opacity=1).add_to(my_map)
                        end_point = seg[-1]
                        nearest_csv_point = self._find_nearest_csv_point(end_point)
                        if nearest_csv_point:
                            lat, lon, label = nearest_csv_point
                            weather = Weather(lat, lon, start_date, end_date)
                            weather_data = weather.weather_data()
                            for date, avg_temp, description in weather_data:
                                if previous_end_point:
                                    distance_from_last = geodesic(previous_end_point, (lat, lon)).miles
                                    marker_text = f"{label} DAY {DAY}: Distance from last: {distance_from_last:.2f} miles, Weather: {avg_temp}F, {description}"
                                else:
                                    marker_text = f"{label} DAY {DAY}: Distance: {geodesic((seg[0][0], seg[0][1]), (lat, lon)).miles:.2f} miles, Weather: {avg_temp}F, {description}"
                                folium.Marker(location=[lat, lon], popup=marker_text,
                                              icon=folium.Icon(color='red')).add_to(my_map)
                            previous_end_point = (lat, lon)
                            DAY += 1


        # Save map to HTML
        my_map.save(output_file)
        return output_file


def segment_gpx_by_max_elevation_change(gpx_file, max_elevation_change_feet):
    """
    Segments a GPX file's track into multiple track segments based on a maximum elevation change threshold.

    Args:
        gpx_file (str): Path to the GPX file.
        max_elevation_change_feet (float): Maximum total elevation change (in feet) per track segment.

    Returns:
        gpxpy.gpx.GPX: A GPX object containing the segmented tracks.
    """
    # Conversion constant: 1 meter = 3.28084 feet
    METERS_TO_FEET = 3.28084

    # Parse the GPX file
    with open(gpx_file, 'r') as f:
        gpx = gpxpy.parse(f)

    # Create a new segmented GPX object
    segmented_gpx = gpxpy.gpx.GPX()

    for track in gpx.tracks:
        new_track = gpxpy.gpx.GPXTrack()
        segmented_gpx.tracks.append(new_track)

        for segment in track.segments:
            current_segment = gpxpy.gpx.GPXTrackSegment()
            new_track.segments.append(current_segment)

            total_elevation_change = 0
            previous_elevation = None

            for point in segment.points:
                if previous_elevation is not None:
                    elevation_change_feet = abs(point.elevation - previous_elevation) * METERS_TO_FEET
                    total_elevation_change += elevation_change_feet

                    # Check if total elevation change exceeds the max threshold
                    if total_elevation_change >= max_elevation_change_feet:
                        # Start a new segment
                        current_segment = gpxpy.gpx.GPXTrackSegment()
                        new_track.segments.append(current_segment)
                        total_elevation_change = 0  # Reset elevation change for the new segment

                # Add the current point to the current segment
                current_segment.points.append(point)
                previous_elevation = point.elevation

    return segmented_gpx


def create_map_with_segment_markers(segmented_gpx, start_date, end_date, ):
    """
    Creates a folium map visualizing segmented GPX tracks and adds markers for each segment
    showing total elevation change.

    Args:
        segmented_gpx (gpxpy.gpx.GPX): A GPX object with segmented tracks.

    Returns:
        folium.Map: A folium map object with the GPX segments and elevation change markers plotted.
    """
    # Initialize the folium map object centered on the first point of the first segment
    start_lat = segmented_gpx.tracks[0].segments[0].points[0].latitude
    start_lon = segmented_gpx.tracks[0].segments[0].points[0].longitude
    gpx_map = folium.Map(location=[start_lat, start_lon], zoom_start=13)

    # Add each segment to the map with a different color
    colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink']
    color_index = 0
    Day = 1

    for track in segmented_gpx.tracks:
        for segment_index, segment in enumerate(track.segments):
            # Extract the point coordinates
            points = [(point.latitude, point.longitude) for point in segment.points]
            if not points:  # Skip empty segments
                continue

            # Calculate total elevation change for the segment
            elevation_changes = [
                abs(segment.points[i].elevation - segment.points[i - 1].elevation)
                for i in range(1, len(segment.points))
            ]
            total_elevation_change = sum(elevation_changes) * 3.28084  # Convert to feet

            # Draw a polyline for the segment
            folium.PolyLine(
                points,
                color=colors[color_index % len(colors)],  # Cycle through predefined colors
                weight=5,
                opacity=0.8
            ).add_to(gpx_map)

            # Add a marker with total elevation change to the middle of the segment
            midpoint_index = len(points) // 2
            midpoint_latlon = points[midpoint_index]
            latitude = midpoint_latlon[0]
            longitude = midpoint_latlon[1]
            weather = Weather(latitude, longitude, start_date, end_date)
            weather_data = weather.weather_data()
            for date, avg_temp, description in weather_data:
                folium.Marker(
                    location=midpoint_latlon,
                    popup=f"Day {segment_index + 1}: Total Elevation Change: {total_elevation_change:.2f} ft, Weather: {avg_temp}F, {description}",
                    icon=folium.Icon(color='red', icon='info-sign')
                ).add_to(gpx_map)

            color_index += 1
            Day += 1

        with open("camp2.csv", "r") as file:
            reader = csv.reader(file)
            next(reader)
            for row in reader:
                try:
                    # Extract latitude, longitude, and any other relevant data
                    latitude = float(row[0])
                    longitude = float(row[1])
                    popup_text = row[2]  # Example: using the third column for popup text

                    # Add a marker to the map for each row
                    folium.Marker(
                        location=[latitude, longitude],
                        popup=popup_text,
                        icon=folium.Icon(color='blue', icon='info-sign')
                    ).add_to(gpx_map)
                except ValueError:
                    print(f"Skipping row with invalid data: {row}")

    return gpx_map


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico')

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        miles_per_day = float(request.form['miles_per_day'])
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        split_by = request.form['split_by']
        year_to_subtract = 1

        # Parse the dates correctly
        start_date_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')

        # Subtract years
        start_date_last_year = start_date_dt - relativedelta(years=year_to_subtract)
        end_date_last_year = end_date_dt - relativedelta(years=year_to_subtract)

        max_miles = miles_per_day
        min_miles = miles_per_day - 1

        gpx_file = 'John Muir Trail-2.gpx'
        csv_file = 'camp2.csv'
        map_file = 'static/map.html'
        gpx_to_map = GPXToMap(gpx_file, csv_file)

        # Pass the dates as strings
        if split_by == 'distance':
            gpx_to_map.create_map(max_miles, min_miles, start_date_last_year.strftime('%Y-%m-%d'),
                                  end_date_last_year.strftime('%Y-%m-%d'))
        else:
            try:
                max_elevation_change_feet = float(request.form['max_elevation_gain'])
                segmented_gpx_data = segment_gpx_by_max_elevation_change(gpx_file, max_elevation_change_feet)
                gpx_map = create_map_with_segment_markers(segmented_gpx_data, start_date_last_year.strftime('%Y-%m-%d'),
                                                          end_date_last_year.strftime('%Y-%m-%d'))
                gpx_map.save('static/map.html')
            except ValueError:
                return "Invalid elevation gain values provided."

        return render_template_string('''
        <html>
        <style>
        h1 {text-align: center;}
        body {background: linear-gradient(to top, #d735ba, #ffffff);
        font-family: "Trebuchet MS", sans-serif;)}
        </style>
            <h1><img src= '/static/header.svg'/></h1>
            <h1><img src = '/static/mc.svg'></h1>
            <iframe src="{{ url_for('static', filename='map.html') }}" width="100%" height="600"></iframe>
            <br><br>
            <a href="/">Create Another Map</a>
        ''', map_file=map_file)

    return '''
    <html>
    <style>
    h1 {text-align: center;}
    div {text-align: center;}
    div {color: #d735ba;}
    body {background: linear-gradient(to top, #d735ba, #ffffff);
    font-family: "Trebuchet MS", sans-serif;)}
    </style>
    <h1><img src= '/static/header.svg'/></h1>
 
    <div class="container">
           <p1 style="color:18baf5">MAPPY is a project that assists JMT through-hikers by utilizing Python and its free libraries to create an interactive map with segments based on miles or elevation. The miles-based map will guide hikers to the nearest camping spot using user data from FarOut and weather information from the OpenWeather API. Although this feature could not be implemented in the elevation map, it still provides camping and weather data. The segment markers are red for both maps, while the camping data is shown in blue.
I look forward to adding more features as the development team progresses.</p1>
<br><br>

    <form method="post">
    <label for="miles_per_day">Enter Miles Per Day:</label>
    <input type="range" id="miles_per_day" name="miles_per_day" min="1" max="30" value="15" oninput="this.nextElementSibling.value = this.value">
    <output>20</output><br>

    <label for="start_date">Enter Start Date:</label>
    <input type="date" id="start_date" name="start_date" required><br>

    <label for="end_date">Enter End Date:</label>
    <input type="date" id="end_date" name="end_date" required><br>

    <p id="date_warning" style="color:red; display:none;">Start Date cannot be later than End Date.</p>

    <label for="split_by">Split By:</label>
    <select id="split_by" name="split_by" onchange="toggleElevationFields(this.value)">
        <option value="distance">Distance</option>
        <option value="elevation">Elevation Gain</option>
    </select><br>

    <div id="elevation_fields" style="display:none;">
        <label for="max_elevation_gain">Enter Max Elevation Gain (Feet):</label>
        <input type="range" id="max_elevation_gain" name="max_elevation_gain" min="0" max="10000" value="4500" oninput="this.nextElementSibling.value = this.value">
    <output>4500</output><br>
    </div>

    <input type="submit" value="Create Map">
</form>
        <script>
            function toggleElevationFields(value) {
                var elevationFields = document.getElementById('elevation_fields');
                if (value === 'elevation') {
                    elevationFields.style.display = 'block';
                } else {
                    elevationFields.style.display = 'none';
                }
                var startDate = document.getElementById('start_date');
                var endDate = document.getElementById('end_date');
                if (startDate.value && endDate.value && new Date(startDate.value) > new Date(endDate.value)) {
                    document.getElementById('date_warning').style.display = 'block';
                } else {
                    document.getElementById('date_warning').style.display = 'none';
                }
            }
        </script>
    </div>
    '''


if __name__ == '__main__':
    app.run()
