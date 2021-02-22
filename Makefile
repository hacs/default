.DEFAULT_GOAL := help

help: ## Shows help message.
	@printf "\033[1m%s\033[36m %s\033[32m %s\033[0m \n\n" "Development environment for" "HACS" "Default";
	@awk 'BEGIN {FS = ":.*##";} /^[a-zA-Z_-]+:.*?##/ { printf " \033[36m make %-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST);
	@echo

init:
	python3 -m pip install setuptools wheel
	python3 -m pip install -r requirements.txt

add: ## Add a new repository to the default HACS list
	@bash scripts/add;

remove: ## Remove a repository to the default HACS list
	@bash scripts/remove;

update: ## Pull master from hacs/default
	@ git pull upstream master;

sort: ## Sort all files
	python3 scripts/sort.py;