set(WIFI_ENV_FILE "${PROJECT_DIR}/.env")
if(NOT EXISTS "${WIFI_ENV_FILE}")
	message(FATAL_ERROR ".env missing")
endif()

set(APP_WIFI_SSID "")
set(APP_WIFI_PASSWORD "")
set(APP_CLOUD_BASE_URL "")

file(STRINGS "${WIFI_ENV_FILE}" WIFI_ENV_LINES)
foreach(line IN LISTS WIFI_ENV_LINES)
	string(STRIP "${line}" line)
	if(line MATCHES "^export[ \t]+APP_WIFI_SSID=\"(.*)\"$")
		set(APP_WIFI_SSID "${CMAKE_MATCH_1}")
	elseif(line MATCHES "^export[ \t]+APP_WIFI_PASSWORD=\"(.*)\"$")
		set(APP_WIFI_PASSWORD "${CMAKE_MATCH_1}")
	elseif(line MATCHES "^export[ \t]+APP_CLOUD_BASE_URL=\"(.*)\"$")
		set(APP_CLOUD_BASE_URL "${CMAKE_MATCH_1}")
	endif()
endforeach()

if("${APP_WIFI_SSID}" STREQUAL "" OR "${APP_WIFI_PASSWORD}" STREQUAL "")
	message(FATAL_ERROR "APP_WIFI_SSID/APP_WIFI_PASSWORD not in .env")
endif()

string(REPLACE "\\" "\\\\" APP_WIFI_SSID_ESC "${APP_WIFI_SSID}")
string(REPLACE "\"" "\\\"" APP_WIFI_SSID_ESC "${APP_WIFI_SSID_ESC}")
string(REPLACE "\\" "\\\\" APP_WIFI_PASSWORD_ESC "${APP_WIFI_PASSWORD}")
string(REPLACE "\"" "\\\"" APP_WIFI_PASSWORD_ESC "${APP_WIFI_PASSWORD_ESC}")
string(REPLACE "\\" "\\\\" APP_CLOUD_BASE_URL_ESC "${APP_CLOUD_BASE_URL}")
string(REPLACE "\"" "\\\"" APP_CLOUD_BASE_URL_ESC "${APP_CLOUD_BASE_URL_ESC}")

idf_component_register(
	SRCS "shell.c" "relay.c" "wifi.c" "cloud_client.c" "main.c"
	INCLUDE_DIRS "."
	REQUIRES esp_wifi esp_event esp_netif nvs_flash esp_http_client esp_driver_gpio esp_timer mbedtls
)

target_compile_definitions(${COMPONENT_LIB} PRIVATE
	WIFI_SSID=\"${APP_WIFI_SSID_ESC}\"
	WIFI_PASSWORD=\"${APP_WIFI_PASSWORD_ESC}\"
	CLOUD_BASE_URL="${APP_CLOUD_BASE_URL_ESC}"
)