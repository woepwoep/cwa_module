# -*- coding: utf-8 -*-
from openerp import models, fields, api
import ftplib
import os
import re
import math
from lxml import etree
import types
import datetime
from constants import *
import logging
_logger = logging.getLogger(__name__)


class cwa_import_module(models.Model):
    _name = 'cwa.import'
        
    def connect_to_ftp(self, address, usr, pwd):
        ftp = ftplib.FTP(address)
        ftp.login(usr, pwd)
        return ftp
    
    def disconnect_from_ftp(self, ftp):
        ftp.quit()
        return True
        
    def download_ftp_files(self, tmp, ftp, todo, done):
        ftp.cwd(done)
        processed_files = ftp.nlst()
        ftp.cwd(todo)
        todo_files = ftp.nlst()
        if not os.path.exists('/tmp/%s' % tmp):
            os.mkdir('/tmp/%s' % tmp)
        for f in todo_files:
            if f not in processed_files:
                ftp.retrbinary("RETR %s" % f, open('/tmp/%s/%s' % (tmp, f), 'wb').write)     
        return True
    
    def move_ftp_files(self, tmp, ftp, todo, done):
        processed_files = os.listdir('/tmp/%s' % tmp)
        for f in processed_files:
            ftp.rename('%s/%s' % (todo, f), '%s/%s' % (done, f))
        return True
    
    def parse_xml_products(self, cr, uid, f):
        product_template_obj = self.pool.get('product.template')
        irmodel_data_obj = self.pool.get('ir.model.data')
        products = []
        product_tags = ['id', 'name', 'list_price', 'ean13', 'categ_id/id', 
                        'taxes_id', 'supplier_taxes_id', 'available_in_pos', 
                        'uom_id/id', 'uom_po_id/id', 'pos_categ_id/id', 'cwa_product', 
                        'use_deposit', 'select_deposit/id', 'to_weight', 'type']
        root = etree.parse(f).getroot()
        
        for product in root.iter('product'):
            temp_data = {}
            for item in product:
                if item.tag not in product_tags:
                    product_tags.append(item.tag)
                if type(item.text) is types.NoneType:
                    temp_data[item.tag] = "NONE"
                else:
                    temp_data[item.tag] = item.text.encode('utf-8').upper()
                
            temp_data['id'] = self.set_external_id(temp_data)
            temp_data['ean13'] = 0 if temp_data['eancode'] == "NONE" else self.set_ean_code(temp_data['eancode'])
            temp_data['name'] = temp_data['omschrijving']
            temp_data['list_price'] = float(temp_data['consumentenprijs'])
            temp_data['categ_id/id'] = "cwa_cbl_cat.%s" % temp_data['cblcode']
            temp_data['taxes_id'] = 'Verkopen/omzet hoog' if temp_data['btw'] == '21' else 'Verkopen/omzet laag'
            temp_data['supplier_taxes_id'] = 'BTW te vorderen hoog (inkopen)' if temp_data['btw'] == '21' else 'BTW te vorderen laag (inkopen)'
            temp_data['available_in_pos'] = 'false'
            temp_data['pos_categ_id/id'] = 'cwa_module.cwa_pos_categ_%s' % (temp_data['cblcode'][:5])
            temp_data['cwa_product'] = 'true'
            temp_data['to_weight'] = 'true' if temp_data['weegschaalartikel'] == '1' else 'false'
            temp_data['type'] = 'product'
            try:
                temp_data['use_deposit'] = 'true' if statiegeld_translations[temp_data['statiegeld']] != 0 else 'false'
                temp_data['select_deposit/id'] = statiegeld_translations[temp_data['statiegeld']] if temp_data['use_deposit'] != 'false' else 0
            except KeyError:
                temp_data['use_deposit'] = 'false'
                temp_data['select_deposit/id'] = 0                
            try:
                temp_data['uom_id/id'] = uom_translations[temp_data['verpakkingce']]
                temp_data['uom_po_id/id'] = uom_translations[temp_data['verpakkingce']]
            except KeyError:
                temp_data['uom_id/id'] = uom_translations['STUKS']
                temp_data['uom_po_id/id'] = uom_translations['STUKS']
        
            temp_list = []
            for tag in product_tags:
                try:
                    temp_list.append(temp_data[tag])
                except KeyError:
                    temp_list.append("NONE")
            
            #check if product already exists in the db
            shared_name_ids = irmodel_data_obj.search(cr, uid, [('name', '=', temp_data['id'])])
            product_exists = False
            for product in products:
                if product[3] == temp_data['eancode']:
                    product_exists = True
                    break
                
            if product_exists or len(shared_name_ids) > 0:
                continue
            products.append(temp_list)
        return products, product_tags
    
    def parse_xml_supplier_info(self, f):
        root = etree.parse(f).getroot()
        supplier_info = []
        supplier_info_tags = ['id', 'name/id', 'product_tmpl_id/id', 'pos_categ_id']
        
        for product in root.iter('product'):
            temp_data = {}
            for item in product:
                if item.tag not in supplier_info_tags:
                    supplier_info_tags.append(item.tag)
                if type(item.text) is types.NoneType:
                    temp_data[item.tag] = "NONE"
                else:
                    temp_data[item.tag] = item.text.encode('utf-8').upper()
                    
            temp_data['id'] = 'supplier_info_%s_%s' % (temp_data['leveranciernummer'], temp_data['bestelnummer'])
            temp_data['name/id'] = 'cwa_module.supplier_code_%s' % (temp_data['leveranciernummer'])
            temp_data['product_tmpl_id/id'] = self.set_external_id(temp_data)
            temp_data['pos_categ_id'] = "cwa_module.cwa_pos_categ_%s" % temp_data['cblcode'][:5]
                
            temp_list = []
            for tag in supplier_info_tags:
                try:
                    temp_list.append(temp_data[tag])
                except KeyError:
                    temp_list.append("NONE")
            supplier_info.append(temp_list)
        return supplier_info, supplier_info_tags
                
                
    def set_external_id(self, data):
        if data['eancode'].lower() == 'none' or data['eancode'] == '0000000000000':
            return 'product_ex_id_%s_%s' % (data['leveranciernummer'], data['bestelnummer'])
        else:
            return 'product_ex_id_%s' % (data['eancode'])
    
    def set_ean_code(self, ean):
        return sanitize_ean13(ean)
            
    def split_data(self, data):
        split_size = 50
        return [data[x:x+split_size] for x in range(0, len(data), split_size)]
        
    def load_records(self, cr, uid, tags, data, model):
        data = self.split_data(data)
        for d in data:
            new_cr = self.pool.cursor()
            x = self.pool.get(model).load(new_cr, uid, tags, d)
            new_cr.commit()
            new_cr.close()
            if len(x['messages']) > 0:
                _logger.error(x)
            else:
                _logger.warning(x)
        return True
    
    def gen_tmp_name(self):
        tmp = 'cwa_import_%s' % datetime.datetime.now().isoformat().replace(':', '').replace('-', '').replace('.', '')
        return tmp

    def write_log(self, log_data):
        with open('error_log.txt', 'a') as f:
            f.write(str(log_data)+'\n\n')
    
    def run(self, cr, uid):
        ''' 
        params[0] = ip address
        params[1] = uid
        params[2] = pwd
        params[3] = todo directory
        params[4] = done directory 
        '''
        pre_time = datetime.datetime.now()
        _logger.warning("Getting arguments")
        params = self.pool['ir.config_parameter'].get_param(cr, uid, 'cwa.import.ftp_info').split(';')
        _logger.warning(params)
        _logger.warning("Connecting to ftp")
        ftp = self.connect_to_ftp(params[0], params[1], params[2]) # returns ftp connection instance
        tmp = self.gen_tmp_name()
        _logger.warning("Downloading files")
        self.download_ftp_files(tmp, ftp, params[3], params[4])
        self.disconnect_from_ftp(ftp)
        _logger.warning("Parsing files")
        for f in os.listdir('/tmp/%s' % tmp):
            _logger.warning("Parsing products")
            product_info = self.parse_xml_products(cr, uid, '/tmp/%s/%s'%(tmp, f))
            _logger.warning("Parsing supplier info")
            supplier_info = self.parse_xml_supplier_info('/tmp/%s/%s'%(tmp, f))
            _logger.warning("Loading products")
            self.load_records(cr, uid, product_info[1], product_info[0], 'product.template')
            _logger.warning("Loading supplierinfo")
            self.load_records(cr, uid, supplier_info[1], supplier_info[0], 'product.supplierinfo')
        _logger.warning("Moving files")
        ftp = self.connect_to_ftp(params[0], params[1], params[2])
        self.move_ftp_files(tmp, ftp, params[3], params[4])
        ftp.quit()
        post_time = datetime.datetime.now()
        time_delta = post_time - pre_time
        _logger.warning("Done")
        _logger.warning("Took: %s" % str(time_delta))
        return True


class extended_supplierinfo(models.Model):
    _inherit = 'product.supplierinfo'
    
    eancode =           fields.Char('eancode', help="eancode")
    omschrijving =      fields.Char('omschrijving', help="omschrijving")
    weegschaalartikel = fields.Char('weegschaalartikel', help="1 = waar/0 = niet waar")
    wichtartikel =      fields.Char('wichtartikel', help="1 = waar/0 = niet waar")
    pluartikel =        fields.Char('pluartikel', help="1 = waar/0 = niet waar")
    inhoud =            fields.Char('inhoud', help="Inhoud van de verpakking.")
    eenheid =           fields.Char('eenheid', help="Aanduiding van de inhoud.")
    verpakkingce =      fields.Char('verpakkingce', help="Verpakking van consumenten eenheid.")
    merk =              fields.Char('merk', help="merk")
    kwaliteit =         fields.Char('kwaliteit', help="Kwaliteitsaanduiding")
    btw =               fields.Char('btw', help="BTW percentage 0, 6 of 21")
    cblcode =           fields.Char('cblcode', help="cblcode")
    leveranciernummer = fields.Char('leveranciernummer', help="Identificerend nummer van een leverancier.")
    bestelnummer =      fields.Char('bestelnummer', help="Bestelnummer van artikel bij leverancier.")
    proefdiervrij =     fields.Char('proefdiervrij', help="0=onbekend / 1=ja / 2=nee")
    vegetarisch =       fields.Char('vegetarisch', help="0=onbekend / 1=ja / 2=nee")
    veganistisch =      fields.Char('veganistisch', help="0=onbekend / 1=ja / 2=nee")
    rauwemelk =         fields.Char('rauwemelk', help="0=onbekend / 1=ja / 2=nee")
    inkoopprijs =       fields.Char('inkoopprijs', help="inkoopprijs")
    consumentenprijs =  fields.Char('consumentenprijs', help="consumentenprijs")
    ingangsdatum =      fields.Char('ingangsdatum', help="Datum in de vorm eejj-mm-dd")
    herkomst =          fields.Char('herkomst', help="Land van herkomst in vorm ISO 3166 code.")
    ingredienten =      fields.Char('ingredienten', help="Beschrijving van de ingredienten.")
    statiegeld =        fields.Char('statiegeld', help="bedrag")
    kassaomschrijving = fields.Char('kassaomschrijving', help="Korte omschrijving van het product tbv de kassa")
    plucode =           fields.Char('plucode', help="4cijferige plucode.")
    sve =               fields.Char('sve', help="Standaard verpakkings eenheid bij leverancier.")
    status =            fields.Char('status', help="Mogelijke waarden: Actief/Non Actief/Gesaneerd")
    keurmerkbio =       fields.Char('keurmerkbio', help="keurmerkbio")
    keurmerkoverig =    fields.Char('keurmerkoverig', help="keurmerkoverig")
    herkomstregio =     fields.Char('herkomstregio', help="herkokmstregio")
    aantaldagenhoudbaar=fields.Char('aantaldagenhoudbaar', help="aantaldagenhoudbaar")
    bewaartemperatuur = fields.Char('bewaartemperatuur', help="bewaartemperatuur")
    gebruikstips =      fields.Char('gebruikstips', help="gebruikstips")
    lengte =            fields.Char('lengte', help="lengte")
    breedte =           fields.Char('breedte', help="breedte")
    hoogte =            fields.Char('hoogte', help="hoogte")
    code =              fields.Char('code', help="code")
    d204 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d204', help="Cacao", readonly=True)
    d209 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d209', help="Glutamaat", readonly=True)
    d210 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d210', help="Gluten", readonly=True)
    d212 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d212', help="Ei", readonly=True)
    d213 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d213', help="Kip", readonly=True)
    d214 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d214', help="Melk", readonly=True)
    d234 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d234', help="Koriander", readonly=True)
    d215 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d215', help="Lactose", readonly=True)
    d239 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d239', help="Lupine", readonly=True)
    d216 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d216', help="Mais", readonly=True)
    d217 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d217', help="Noten", readonly=True)
    d217b =             fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d217b', help="Notenolie", readonly=True)
    d220 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d220', help="Peulvruchten", readonly=True)
    d221 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d221', help="Pinda", readonly=True)
    d221b =             fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d221b', help="Pindaolie", readonly=True)
    d222 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d222', help="Rogge", readonly=True)
    d223 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d223', help="Rundvlees", readonly=True)
    d236 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d236', help="Schaaldieren", readonly=True)
    d235 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d235', help="Selderij", readonly=True)
    d238 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d238', help="Sesam", readonly=True)
    d238b =             fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d238b', help="Sesamolie", readonly=True)
    d225 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d225', help="Soja", readonly=True)
    d226 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d226', help="Soja-olie", readonly=True)
    d228 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d228', help="Sulfiet", readonly=True)
    d230 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d230', help="Tarwe", readonly=True)
    d232 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d232', help="Varkensvlees", readonly=True)
    d237 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d237', help="Vis", readonly=True)
    d240 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d240', help="Wortel", readonly=True)
    d241 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d241', help="Mosterd", readonly=True)
    d242 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d242', help="Weekdieren", readonly=True)
    pos_categ_id =      fields.Char('NOT A REFERENCE', help="Not a reference field, just a char field.")
    
    
class extended_template(models.Model):
    _inherit = 'product.template'

    eancode =           fields.Char('eancode', help="eancode")
    omschrijving =      fields.Char('omschrijving', help="omschrijving")
    weegschaalartikel = fields.Char('weegschaalartikel', help="1 = waar/0 = niet waar")
    wichtartikel =      fields.Char('wichtartikel', help="1 = waar/0 = niet waar")
    pluartikel =        fields.Char('pluartikel', help="1 = waar/0 = niet waar")
    inhoud =            fields.Char('inhoud', help="Inhoud van de verpakking.")
    eenheid =           fields.Char('eenheid', help="Aanduiding van de inhoud.")
    verpakkingce =      fields.Char('verpakkingce', help="Verpakking van consumenten eenheid.")
    merk =              fields.Char('merk', help="merk")
    kwaliteit =         fields.Char('kwaliteit', help="Kwaliteitsaanduiding")
    btw =               fields.Char('btw', help="BTW percentage 0, 6 of 21")
    cblcode =           fields.Char('cblcode', help="cblcode")
    leveranciernummer = fields.Char('leveranciernummer', help="Identificerend nummer van een leverancier.")
    bestelnummer =      fields.Char('bestelnummer', help="Bestelnummer van artikel bij leverancier.")
    proefdiervrij =     fields.Char('proefdiervrij', help="0=onbekend / 1=ja / 2=nee")
    vegetarisch =       fields.Char('vegetarisch', help="0=onbekend / 1=ja / 2=nee")
    veganistisch =      fields.Char('veganistisch', help="0=onbekend / 1=ja / 2=nee")
    rauwemelk =         fields.Char('rauwemelk', help="0=onbekend / 1=ja / 2=nee")
    inkoopprijs =       fields.Char('inkoopprijs', help="inkoopprijs")
    consumentenprijs =  fields.Char('consumentenprijs', help="consumentenprijs")
    ingangsdatum =      fields.Char('ingangsdatum', help="Datum in de vorm eejj-mm-dd")
    herkomst =          fields.Char('herkomst', help="Land van herkomst in vorm ISO 3166 code.")
    ingredienten =      fields.Char('ingredienten', help="Beschrijving van de ingredienten.")
    statiegeld =        fields.Char('statiegeld', help="bedrag")
    kassaomschrijving = fields.Char('kassaomschrijving', help="Korte omschrijving van het product tbv de kassa")
    plucode =           fields.Char('plucode', help="4cijferige plucode.")
    sve =               fields.Char('sve', help="Standaard verpakkings eenheid bij leverancier.")
    status =            fields.Char('status', help="Mogelijke waarden: Actief/Non Actief/Gesaneerd")
    keurmerkbio =       fields.Char('keurmerkbio', help="keurmerkbio")
    keurmerkoverig =    fields.Char('keurmerkoverig', help="keurmerkoverig")
    herkomstregio =     fields.Char('herkomstregio', help="herkokmstregio")
    aantaldagenhoudbaar=fields.Char('aantaldagenhoudbaar', help="aantaldagenhoudbaar")
    bewaartemperatuur = fields.Char('bewaartemperatuur', help="bewaartemperatuur")
    gebruikstips =      fields.Char('gebruikstips', help="gebruikstips")
    lengte =            fields.Char('lengte', help="lengte")
    breedte =           fields.Char('breedte', help="breedte")
    hoogte =            fields.Char('hoogte', help="hoogte")
    code =              fields.Char('code', help="code")
    d204 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d204', help="Cacao", default="0")
    d209 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d209', help="Glutamaat", default="0")
    d210 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d210', help="Gluten", default="0")
    d212 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d212', help="Ei", default="0")
    d213 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d213', help="Kip", default="0")
    d214 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d214', help="Melk", default="0")
    d234 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d234', help="Koriander", default="0")
    d215 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d215', help="Lactose", default="0")
    d239 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d239', help="Lupine", default="0")
    d216 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d216', help="Mais", default="0")
    d217 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d217', help="Noten", default="0")
    d217b =             fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d217b', help="Notenolie", default="0")
    d220 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d220', help="Peulvruchten", default="0")
    d221 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d221', help="Pinda", default="0")
    d221b =             fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d221b', help="Pindaolie", default="0")
    d222 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d222', help="Rogge", default="0")
    d223 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d223', help="Rundvlees", default="0")
    d236 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d236', help="Schaaldieren", default="0")
    d235 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d235', help="Selderij", default="0")
    d238 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d238', help="Sesam", default="0")
    d238b =             fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d238b', help="Sesamolie", default="0")
    d225 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d225', help="Soja", default="0")
    d226 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d226', help="Soja-olie", default="0")
    d228 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d228', help="Sulfiet", default="0")
    d230 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d230', help="Tarwe", default="0")
    d232 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d232', help="Varkensvlees", default="0")
    d237 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d237', help="Vis", default="0")
    d240 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d240', help="Wortel", default="0")
    d241 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d241', help="Mosterd", default="0")
    d242 =              fields.Selection([('0','onbekend'),('1','aanwezig'),('2','niet aanwezig'),('3','mogelijk aanwezig')],'d242', help="Weekdieren", default="0")
    cwa_product =       fields.Boolean('Is CWA product?', default=False, readonly=True)
    
    @api.one
    def _compute_inkoopprijs(self):
        try:
            self.inkoopprijs = self.seller_ids[0].inkoopprijs
        except:
            _logger.warning("Could not set inkoopprijs")

    @api.one        
    def _compute_bestelnummer(self):
        try:
            self.bestelnummer = self.seller_ids[0].bestelnummer
        except:
            _logger.warning("Could not set bestelnummer")

    @api.one       
    def _compute_consumentenprijs(self):
        try:
            self.consumentenprijs = self.seller_ids[0].consumentenprijs
        except:
            _logger.warning("Could not set consumentenprijs")


#############################################################################################################
#                                                                                                           #
#                           These two functions are copied from the product model                           #
#                                                                                                           #
#############################################################################################################
def sanitize_ean13(ean13):
    """Creates and returns a valid ean13 from an invalid one"""
    if not ean13:
        return "0000000000000"
    ean13 = re.sub("[A-Za-z]","0",ean13);
    ean13 = re.sub("[^0-9]","",ean13);
    ean13 = ean13[:13]
    if len(ean13) < 13:
        ean13 = ean13 + '0' * (13-len(ean13))
    return ean13[:-1] + str(ean_checksum(ean13))

def ean_checksum(eancode):
    """returns the checksum of an ean string of length 13, returns -1 if the string has the wrong length"""
    if len(eancode) != 13:
        return -1
    oddsum=0
    evensum=0
    total=0
    eanvalue=eancode
    reversevalue = eanvalue[::-1]
    finalean=reversevalue[1:]
    
    for i in range(len(finalean)):
        if i % 2 == 0:
            oddsum += int(finalean[i])
        else:
            evensum += int(finalean[i])
    total=(oddsum * 3) + evensum
    
    check = int(10 - math.ceil(total % 10.0)) %10
    return check

#############################################################################################################
