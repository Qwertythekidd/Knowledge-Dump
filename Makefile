.PHONY: dev build check gateway native

dev:
	npm run dev

build:
	npm run build

check:
	npm run check

gateway:
	python3 -m apps.gateway.knowledge_dump_gateway

native:
	cd apps/desktop-native && cargo run
