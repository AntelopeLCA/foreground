# coding: utf-8
from antelope_foreground import ForegroundCatalog
from antelope import enum
cat = ForegroundCatalog.make_tester()
cat.blackbook_authenticate('http://localhost:80', 'demo_modeler', 'snake_h8ndler')
cat.get_blackbook_resources('demo.ecoinvent')
cat.get_blackbook_resources('lcia.traci.2.1')
truck = cat.query('demo.ecoinvent').get('7f3ade03-f000-447b-a343-59305432a0bb')
fg = cat.create_foreground('lookee')
t = fg.create_process_model(truck)
fg.extend_process(t)
gwp = cat.query('lcia.traci.2.1').get('Global Warming Air')
gwp.do_lcia(truck.lci()).total()
t.fragment_lcia(gwp).total()
gwp.do_lcia(truck.lci()).total()
t.fragment_lcia(gwp).show_components()
