#pragma once

#include "esp_err.h"

esp_err_t relay_init(void);
esp_err_t relay_on(void);
esp_err_t relay_off(void);
esp_err_t relay_toggle(void);
bool relay_is_on_state(void);
void relay_print_status(void);