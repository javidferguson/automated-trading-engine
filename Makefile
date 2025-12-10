# Makes a local environment
trades-dev:
	docker-compose -f docker/docker-compose-options-trader.yml build && \
	docker-compose -f docker/docker-compose-options-trader.yml run --service-ports --rm ajj-options-trader
