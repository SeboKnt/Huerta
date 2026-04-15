#pragma once

#include "esp_err.h"
#include <stdbool.h>

esp_err_t cloud_start_heartbeat(void);
esp_err_t cloud_toggle_identify_state(void);
bool cloud_is_identify_active(void);
int cloud_get_last_cpu_load_pct(void);
