package mech

import (
	"os"
	"reflect"
	"strconv"
	"strings"
)

func applyEnv(p Params, name string) Params {
	s := os.Getenv(name)
	if s == "" {
		return p
	}
	v := reflect.ValueOf(&p).Elem()
	for _, kv := range strings.Split(s, ",") {
		k, val, ok := strings.Cut(strings.TrimSpace(kv), "=")
		if !ok {
			continue
		}
		f := v.FieldByName(k)
		if !f.IsValid() || !f.CanSet() {
			continue
		}
		switch f.Kind() {
		case reflect.Float64:
			if x, err := strconv.ParseFloat(val, 64); err == nil {
				f.SetFloat(x)
			}
		case reflect.Bool:
			if x, err := strconv.ParseBool(val); err == nil {
				f.SetBool(x)
			}
		}
	}
	return p
}
