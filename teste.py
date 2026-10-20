from geopy.geocoders import Nominatim

geolocator = Nominatim(user_agent="teste")
location = geolocator.geocode("Avenida Ayrton Senna da Silva, 1500, Praia Grande, SP, Brasil", timeout=10, country_codes='BR')
print(location)